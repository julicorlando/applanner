from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    FinancialTransaction,
    Product,
    ProductStockMovement,
    ProfessionalCommission,
    Sale,
    SaleItem,
)


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


@transaction.atomic
def create_sale(
    *,
    tenant,
    user,
    items,
    payment_method,
    unit=None,
    customer=None,
    professional=None,
    discount=Decimal("0"),
):
    if not items:
        raise ValidationError("A venda precisa ter ao menos um item.")

    normalized=[]
    subtotal=Decimal("0")
    for raw in items:
        product=Product.objects.select_for_update().filter(
            pk=raw["product_id"],
            tenant=tenant,
            active=True,
        ).first()
        if not product:
            raise ValidationError(f"Produto {raw['product_id']} não encontrado.")

        quantity=Decimal(str(raw.get("quantity") or 0))
        if quantity<=0:
            raise ValidationError("Quantidade deve ser maior que zero.")
        if product.stock<quantity:
            raise ValidationError(f"Estoque insuficiente para {product.name}.")

        unit_price=_money(raw.get("unit_price",product.sale_price))
        item_discount=_money(raw.get("discount",0))
        gross=(quantity*unit_price).quantize(Decimal("0.01"))
        total=gross-item_discount
        if total<0:
            raise ValidationError("Desconto do item não pode superar o valor bruto.")

        normalized.append((product,quantity,unit_price,item_discount,total))
        subtotal+=total

    discount=_money(discount)
    total=_money(subtotal-discount)
    if total<0:
        raise ValidationError("Desconto total inválido.")

    sale=Sale.objects.create(
        tenant=tenant,
        unit=unit,
        professional=professional,
        customer=customer,
        user=user,
        subtotal=_money(subtotal),
        discount=discount,
        total=total,
        payment_method=payment_method,
    )

    for product,quantity,unit_price,item_discount,item_total in normalized:
        commission=Decimal("0")
        rate=None
        if professional:
            if product.commission_type==Product.CommissionType.PERCENT:
                rate=product.commission_value
                commission=(item_total*rate/Decimal("100")).quantize(Decimal("0.01"))
            elif product.commission_type==Product.CommissionType.FIXED:
                commission=_money(product.commission_value)

        item=SaleItem.objects.create(
            sale=sale,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            discount=item_discount,
            total=item_total,
            cost_snapshot=product.cost_price,
            commission_amount_snapshot=commission,
        )

        product.stock=product.stock-quantity
        product.save(update_fields=["stock","updated_at"])

        ProductStockMovement.objects.create(
            tenant=tenant,
            product=product,
            sale=sale,
            type=ProductStockMovement.Type.SALE,
            quantity=-quantity,
            balance_after=product.stock,
            user=user,
            reason=f"Venda #{sale.pk}",
        )

        if professional and commission>0:
            ProfessionalCommission.objects.create(
                tenant=tenant,
                professional=professional,
                source_type="product",
                source_id=item.pk,
                gross_amount=item_total,
                rate_percent=rate,
                commission_amount=commission,
            )

    FinancialTransaction.objects.create(
        tenant=tenant,
        type=FinancialTransaction.Type.INCOME,
        description=f"Venda #{sale.pk}",
        amount=total,
        payment_method=payment_method,
        competence_at=timezone.localdate(),
        status=FinancialTransaction.Status.PAID,
        idempotency_key=f"sale:{sale.pk}",
        source_type="sale",
        source_id=sale.pk,
        paid_at=timezone.now(),
    )
    return sale


@transaction.atomic
def cancel_sale(*,sale,user,reason):
    sale=Sale.objects.select_for_update().select_related("tenant").get(pk=sale.pk)
    if sale.status==Sale.Status.CANCELLED:
        return sale

    for item in sale.items.select_related("product").all():
        product=Product.objects.select_for_update().get(pk=item.product_id)
        product.stock=product.stock+item.quantity
        product.save(update_fields=["stock","updated_at"])
        ProductStockMovement.objects.create(
            tenant=sale.tenant,
            product=product,
            sale=sale,
            type=ProductStockMovement.Type.SALE_REVERSAL,
            quantity=item.quantity,
            balance_after=product.stock,
            user=user,
            reason=f"Cancelamento da venda #{sale.pk}: {reason}"[:500],
        )
        ProfessionalCommission.objects.filter(
            tenant=sale.tenant,
            source_type="product",
            source_id=item.pk,
            status=ProfessionalCommission.Status.PENDING,
        ).update(status=ProfessionalCommission.Status.REVERSED)

    FinancialTransaction.objects.filter(
        tenant=sale.tenant,
        source_type="sale",
        source_id=sale.pk,
    ).update(status=FinancialTransaction.Status.CANCELLED,updated_at=timezone.now())

    sale.status=Sale.Status.CANCELLED
    sale.cancel_reason=reason[:500]
    sale.cancelled_by=user
    sale.cancelled_at=timezone.now()
    sale.save(update_fields=["status","cancel_reason","cancelled_by","cancelled_at"])
    return sale


@transaction.atomic
def open_cash_session(*,tenant,user,opening_amount=0,unit=None,notes=""):
    from .models import CashSession
    if CashSession.objects.filter(tenant=tenant,unit=unit,status=CashSession.Status.OPEN).exists():
        raise ValidationError("Já existe um caixa aberto para esta unidade.")
    return CashSession.objects.create(
        tenant=tenant,unit=unit,opened_by=user,opening_amount=_money(opening_amount),
        opened_at=timezone.now(),notes=notes[:500],
    )


@transaction.atomic
def close_cash_session(*,session,user,closing_amount,notes=""):
    from django.db.models import Sum
    from .models import CashSession
    session=CashSession.objects.select_for_update().get(pk=session.pk)
    if session.status!=CashSession.Status.OPEN:
        raise ValidationError("Caixa já está fechado.")
    cash_methods=["cash","dinheiro"]
    income=FinancialTransaction.objects.filter(
        tenant=session.tenant,status=FinancialTransaction.Status.PAID,
        type=FinancialTransaction.Type.INCOME,paid_at__gte=session.opened_at,
        payment_method__in=cash_methods,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    expense=FinancialTransaction.objects.filter(
        tenant=session.tenant,status=FinancialTransaction.Status.PAID,
        type=FinancialTransaction.Type.EXPENSE,paid_at__gte=session.opened_at,
        payment_method__in=cash_methods,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    expected=_money(session.opening_amount+income-expense)
    closing=_money(closing_amount)
    session.closing_amount=closing
    session.expected_amount=expected
    session.difference_amount=_money(closing-expected)
    session.closed_by=user
    session.closed_at=timezone.now()
    session.status=CashSession.Status.CLOSED
    if notes:
        session.notes=(session.notes+"\n"+notes).strip()[:500]
    session.save()
    return session


@transaction.atomic
def pay_commission(*,commission,user):
    commission=ProfessionalCommission.objects.select_for_update().get(pk=commission.pk)
    if commission.status!=ProfessionalCommission.Status.PENDING:
        raise ValidationError("Comissão não está pendente.")
    commission.status=ProfessionalCommission.Status.PAID
    commission.paid_at=timezone.now()
    commission.paid_by=user
    commission.save(update_fields=["status","paid_at","paid_by","updated_at"])
    FinancialTransaction.objects.get_or_create(
        tenant=commission.tenant,
        idempotency_key=f"commission:{commission.pk}",
        defaults={
            "source_type":"professional_commission","source_id":commission.pk,
            "type":FinancialTransaction.Type.EXPENSE,
            "description":f"Comissão · {commission.professional.name}",
            "amount":commission.commission_amount,
            "status":FinancialTransaction.Status.PAID,
            "competence_at":timezone.localdate(),
            "paid_at":timezone.now(),
        },
    )
    return commission
