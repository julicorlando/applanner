from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from finance.models import FinancialTransaction, Product, ProductStockMovement, ProfessionalCommission
from scheduling.models import Appointment

from .models import (
    BarberCommand,
    BarberCommandItem,
    BarberCommandPayment,
    ProfessionalServiceCommission,
)


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


@transaction.atomic
def check_in_appointment(appointment):
    appointment=Appointment.objects.select_for_update().get(pk=appointment.pk)
    if appointment.status in {Appointment.Status.CANCELLED,Appointment.Status.COMPLETED}:
        raise ValidationError("Este agendamento não aceita check-in.")
    appointment.checked_in_at=appointment.checked_in_at or timezone.now()
    appointment.save(update_fields=["checked_in_at","updated_at"])
    return appointment


@transaction.atomic
def start_service(appointment):
    appointment=Appointment.objects.select_for_update().get(pk=appointment.pk)
    if not appointment.checked_in_at:
        appointment.checked_in_at=timezone.now()
    appointment.service_started_at=appointment.service_started_at or timezone.now()
    appointment.status=Appointment.Status.IN_PROGRESS
    appointment.save(update_fields=["checked_in_at","service_started_at","status","updated_at"])
    return appointment


@transaction.atomic
def open_command(*,tenant,user,appointment=None,customer=None,professional=None,notes=""):
    if appointment:
        if appointment.tenant_id!=tenant.id:
            raise ValidationError("Agendamento pertence a outro tenant.")
        existing=BarberCommand.objects.filter(tenant=tenant,appointment=appointment).first()
        if existing:
            return existing
        customer=customer or appointment.customer
        professional=professional or appointment.professional

    return BarberCommand.objects.create(
        tenant=tenant,
        appointment=appointment,
        customer=customer,
        professional=professional,
        notes=notes[:500],
        opened_by=user,
        opened_at=timezone.now(),
    )


def _service_commission(tenant,professional,service,total):
    if not professional or not service:
        return Decimal("0")
    rule=ProfessionalServiceCommission.objects.filter(
        tenant=tenant,
        professional=professional,
        service=service,
        active=True,
    ).first()
    if rule:
        if rule.commission_type==ProfessionalServiceCommission.Type.FIXED:
            return _money(rule.commission_value)
        return _money(total*rule.commission_value/Decimal("100"))
    if professional.commission_percent is not None:
        return _money(total*professional.commission_percent/Decimal("100"))
    return Decimal("0")


@transaction.atomic
def add_service_item(*,command,service,professional=None,quantity=1,unit_price=None,discount=0,primary=False):
    command=BarberCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=BarberCommand.Status.OPEN:
        raise ValidationError("A comanda está fechada.")
    if service.tenant_id!=command.tenant_id:
        raise ValidationError("Serviço pertence a outro tenant.")

    quantity=Decimal(str(quantity))
    price=_money(service.price if unit_price is None else unit_price)
    discount=_money(discount)
    total=_money(quantity*price-discount)
    if quantity<=0 or total<0:
        raise ValidationError("Valores do item são inválidos.")

    professional=professional or command.professional
    commission=_service_commission(command.tenant,professional,service,total)
    item=BarberCommandItem.objects.create(
        command=command,
        tenant=command.tenant,
        item_type=BarberCommandItem.ItemType.SERVICE,
        service=service,
        professional=professional,
        description=service.name,
        quantity=quantity,
        unit_price=price,
        discount_amount=discount,
        total_amount=total,
        commission_amount_snapshot=commission,
        is_primary_service=primary,
    )
    recalculate_command(command)
    return item


@transaction.atomic
def add_product_item(*,command,product,professional=None,quantity=1,unit_price=None,discount=0):
    command=BarberCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=BarberCommand.Status.OPEN:
        raise ValidationError("A comanda está fechada.")
    if product.tenant_id!=command.tenant_id:
        raise ValidationError("Produto pertence a outro tenant.")

    quantity=Decimal(str(quantity))
    price=_money(product.sale_price if unit_price is None else unit_price)
    discount=_money(discount)
    total=_money(quantity*price-discount)
    if quantity<=0 or total<0:
        raise ValidationError("Valores do item são inválidos.")

    commission=Decimal("0")
    rate=None
    professional=professional or command.professional
    if professional:
        if product.commission_type==Product.CommissionType.FIXED:
            commission=_money(product.commission_value)
        elif product.commission_type==Product.CommissionType.PERCENT:
            rate=product.commission_value
            commission=_money(total*rate/Decimal("100"))

    item=BarberCommandItem.objects.create(
        command=command,
        tenant=command.tenant,
        item_type=BarberCommandItem.ItemType.PRODUCT,
        product=product,
        professional=professional,
        description=product.name,
        quantity=quantity,
        unit_price=price,
        discount_amount=discount,
        total_amount=total,
        cost_snapshot=product.cost_price,
        commission_amount_snapshot=commission,
    )
    recalculate_command(command)
    return item


def recalculate_command(command):
    subtotal=sum((item.total_amount for item in command.items.all()),Decimal("0"))
    total=_money(subtotal-command.discount_amount+command.surcharge_amount+command.tip_amount)
    if total<0:
        raise ValidationError("Total da comanda não pode ser negativo.")
    BarberCommand.objects.filter(pk=command.pk).update(
        subtotal=_money(subtotal),
        total_amount=total,
        updated_at=timezone.now(),
    )
    command.subtotal=_money(subtotal)
    command.total_amount=total
    return command


@transaction.atomic
def register_payment(*,command,user,method,amount):
    command=BarberCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=BarberCommand.Status.OPEN:
        raise ValidationError("A comanda está fechada.")
    amount=_money(amount)
    if amount<=0:
        raise ValidationError("Valor do pagamento inválido.")
    return BarberCommandPayment.objects.create(
        command=command,
        tenant=command.tenant,
        method=method[:40],
        amount=amount,
        user=user,
        received_at=timezone.now(),
    )


@transaction.atomic
def close_command(*,command,user):
    command=(
        BarberCommand.objects
        .select_for_update()
        .select_related("appointment","professional","tip_professional","tenant")
        .get(pk=command.pk)
    )
    if command.status==BarberCommand.Status.CLOSED:
        return command
    if command.status!=BarberCommand.Status.OPEN:
        raise ValidationError("Comanda cancelada não pode ser fechada.")

    recalculate_command(command)
    paid=sum((payment.amount for payment in command.payments.all()),Decimal("0"))
    if _money(paid)<command.total_amount:
        raise ValidationError("Pagamentos não cobrem o total da comanda.")

    for item in command.items.select_related("product","service","professional").all():
        if item.item_type==BarberCommandItem.ItemType.PRODUCT and item.product_id:
            product=Product.objects.select_for_update().get(pk=item.product_id)
            if product.stock<item.quantity:
                raise ValidationError(f"Estoque insuficiente para {product.name}.")
            product.stock=product.stock-item.quantity
            product.save(update_fields=["stock","updated_at"])
            ProductStockMovement.objects.create(
                tenant=command.tenant,
                product=product,
                type=ProductStockMovement.Type.COMMAND,
                quantity=-item.quantity,
                balance_after=product.stock,
                user=user,
                reason=f"Comanda #{command.pk}",
            )

        if item.professional_id and item.commission_amount_snapshot and item.commission_amount_snapshot>0:
            ProfessionalCommission.objects.get_or_create(
                tenant=command.tenant,
                professional=item.professional,
                source_type="command_"+item.item_type,
                source_id=item.pk,
                defaults={
                    "gross_amount":item.total_amount,
                    "commission_amount":item.commission_amount_snapshot,
                },
            )

    if command.tip_professional_id and command.tip_amount>0:
        ProfessionalCommission.objects.get_or_create(
            tenant=command.tenant,
            professional=command.tip_professional,
            source_type="tip",
            source_id=command.pk,
            defaults={
                "gross_amount":command.tip_amount,
                "commission_amount":command.tip_amount,
            },
        )

    payment_method="mixed" if command.payments.values("method").distinct().count()>1 else (
        command.payments.values_list("method",flat=True).first() or "other"
    )
    FinancialTransaction.objects.get_or_create(
        tenant=command.tenant,
        source_type="barber_command",
        source_id=command.pk,
        defaults={
            "type":FinancialTransaction.Type.INCOME,
            "description":f"Comanda #{command.pk}",
            "amount":command.total_amount,
            "payment_method":payment_method,
            "competence_at":timezone.localdate(),
            "status":FinancialTransaction.Status.PAID,
            "idempotency_key":f"barber-command:{command.pk}",
            "paid_at":timezone.now(),
        },
    )

    command.status=BarberCommand.Status.CLOSED
    command.closed_by=user
    command.closed_at=timezone.now()
    command.save(update_fields=["status","closed_by","closed_at","updated_at"])

    if command.appointment_id:
        appointment=Appointment.objects.select_for_update().get(pk=command.appointment_id)
        appointment.status=Appointment.Status.COMPLETED
        appointment.service_completed_at=appointment.service_completed_at or timezone.now()
        appointment.save(update_fields=["status","service_completed_at","updated_at"])
    return command
