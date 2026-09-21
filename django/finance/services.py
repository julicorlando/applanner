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
