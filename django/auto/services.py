from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from finance.models import FinancialTransaction, Product, ProductStockMovement, ProfessionalCommission
from scheduling.models import Appointment

from .models import (
    AutoCommand, AutoCommandItem, AutoCommandPayment, CRMEvent, Job, JobMaterialUsage,
    JobStatusHistory, VehicleMaintenance, VehicleProfile,
)


@transaction.atomic
def transition_job(*,job,new_status,user=None,notes=""):
    job=Job.objects.select_for_update().get(pk=job.pk)
    valid={value for value,_ in Job.Status.choices}
    if new_status not in valid:
        raise ValidationError("Status automotivo inválido.")
    old=job.status
    now=timezone.now()
    job.status=new_status
    if new_status==Job.Status.RECEIVED:
        job.received_at=job.received_at or now
    elif new_status==Job.Status.IN_SERVICE:
        job.started_at=job.started_at or now
        Appointment.objects.filter(pk=job.appointment_id).update(status=Appointment.Status.IN_PROGRESS)
    elif new_status==Job.Status.READY:
        job.ready_at=job.ready_at or now
    elif new_status==Job.Status.DELIVERED:
        job.delivered_at=job.delivered_at or now
        Appointment.objects.filter(pk=job.appointment_id).update(
            status=Appointment.Status.COMPLETED,service_completed_at=now
        )
    job.save()
    JobStatusHistory.objects.create(
        tenant=job.tenant,job=job,old_status=old,new_status=new_status,
        user=user,notes=notes[:500],
    )
    return job


@transaction.atomic
def consume_material(*,job,product,quantity,user=None,dilution="",batch_lot="",notes=""):
    quantity=Decimal(str(quantity))
    if quantity<=0:
        raise ValidationError("Quantidade inválida.")
    product=Product.objects.select_for_update().get(pk=product.pk,tenant=job.tenant)
    if product.stock<quantity:
        raise ValidationError(f"Estoque insuficiente para {product.name}.")
    product.stock-=quantity
    product.save(update_fields=["stock","updated_at"])
    ProductStockMovement.objects.create(
        tenant=job.tenant,product=product,type=ProductStockMovement.Type.COMMAND,
        quantity=-quantity,balance_after=product.stock,user=user,
        reason=f"Consumo OS automotiva #{job.pk}",
    )
    return JobMaterialUsage.objects.create(
        tenant=job.tenant,job=job,product=product,quantity=quantity,
        dilution=dilution[:60],batch_lot=batch_lot[:100],notes=notes[:500],created_by=user,
    )


def recalculate_command(command):
    subtotal=sum((item.total_amount for item in command.items.all()),Decimal("0"))
    total=subtotal-command.discount_amount+command.surcharge_amount
    if total<0:
        raise ValidationError("Total da comanda não pode ser negativo.")
    AutoCommand.objects.filter(pk=command.pk).update(
        subtotal=subtotal,total_amount=total,updated_at=timezone.now()
    )
    command.subtotal=subtotal
    command.total_amount=total
    return command


@transaction.atomic
def close_command(*,command,user):
    command=AutoCommand.objects.select_for_update().get(pk=command.pk)
    if command.status==AutoCommand.Status.CLOSED:
        return command
    if command.status!=AutoCommand.Status.OPEN:
        raise ValidationError("Comanda não está aberta.")
    recalculate_command(command)
    paid=sum(command.payments.values_list("amount",flat=True),Decimal("0"))
    if paid<command.total_amount:
        raise ValidationError("Pagamentos não cobrem o total.")

    for item in command.items.select_related("product","professional").all():
        if item.product_id and item.item_type in {AutoCommandItem.Type.PRODUCT,AutoCommandItem.Type.MATERIAL}:
            product=Product.objects.select_for_update().get(pk=item.product_id)
            if product.stock<item.quantity:
                raise ValidationError(f"Estoque insuficiente para {product.name}.")
            product.stock-=item.quantity
            product.save(update_fields=["stock","updated_at"])
            ProductStockMovement.objects.create(
                tenant=command.tenant,product=product,type=ProductStockMovement.Type.COMMAND,
                quantity=-item.quantity,balance_after=product.stock,user=user,
                reason=f"Comanda Auto #{command.pk}",
            )
        if item.professional_id and item.item_type==AutoCommandItem.Type.SERVICE:
            rate=item.professional.commission_percent or Decimal("0")
            commission=(item.total_amount*rate/Decimal("100")).quantize(Decimal("0.01"))
            if commission>0:
                ProfessionalCommission.objects.get_or_create(
                    tenant=command.tenant,professional=item.professional,
                    source_type="auto_service",source_id=item.pk,
                    defaults={
                        "gross_amount":item.total_amount,
                        "rate_percent":rate,
                        "commission_amount":commission,
                    },
                )

    methods=list(command.payments.values_list("payment_method",flat=True).distinct())
    FinancialTransaction.objects.get_or_create(
        tenant=command.tenant,idempotency_key=f"auto-command:{command.pk}",
        defaults={
            "appointment":command.appointment,
            "source_type":"auto_command","source_id":command.pk,
            "type":FinancialTransaction.Type.INCOME,
            "description":f"Comanda automotiva #{command.pk}",
            "amount":command.total_amount,
            "payment_method":methods[0] if len(methods)==1 else "mixed",
            "competence_at":timezone.localdate(),
            "status":FinancialTransaction.Status.PAID,
            "paid_at":timezone.now(),
        },
    )

    command.status=AutoCommand.Status.CLOSED
    command.closed_by=user
    command.closed_at=timezone.now()
    command.save(update_fields=["status","closed_by","closed_at","updated_at"])
    transition_job(job=command.job,new_status=Job.Status.DELIVERED,user=user,notes="Comanda encerrada")

    profile,_=VehicleProfile.objects.get_or_create(vehicle=command.vehicle,defaults={"tenant":command.tenant})
    profile.last_service_at=timezone.now()
    technical=getattr(command.job,"technical",None)
    if technical and technical.return_days:
        profile.next_recommended_at=timezone.localdate()+timedelta(days=technical.return_days)
        CRMEvent.objects.get_or_create(
            tenant=command.tenant,vehicle=command.vehicle,customer=command.customer,
            event_type=CRMEvent.Type.RETURN_DUE,due_at=profile.next_recommended_at,
        )
    if technical and technical.warranty_days:
        profile.warranty_until=timezone.localdate()+timedelta(days=technical.warranty_days)
    profile.save()
    return command


@transaction.atomic
def open_command(*,job,user):
    job=Job.objects.select_for_update().select_related("appointment__customer","vehicle").get(pk=job.pk)
    existing=AutoCommand.objects.filter(job=job).first()
    if existing:
        return existing
    return AutoCommand.objects.create(
        tenant=job.tenant,job=job,appointment=job.appointment,
        customer=job.appointment.customer,vehicle=job.vehicle,
        opened_by=user,opened_at=timezone.now(),
    )


@transaction.atomic
def add_service_item(*,command,service,professional=None,quantity=1,unit_price=None,discount=0):
    command=AutoCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=AutoCommand.Status.OPEN:
        raise ValidationError("Comanda não está aberta.")
    if service.tenant_id!=command.tenant_id:
        raise ValidationError("Serviço pertence a outro tenant.")
    quantity=Decimal(str(quantity))
    price=Decimal(str(service.price if unit_price in (None,"") else unit_price))
    discount=Decimal(str(discount or 0))
    total=(quantity*price-discount).quantize(Decimal("0.01"))
    if quantity<=0 or total<0:
        raise ValidationError("Valores inválidos.")
    item=AutoCommandItem.objects.create(
        command=command,tenant=command.tenant,item_type=AutoCommandItem.Type.SERVICE,
        service=service,professional=professional,description=service.name,
        quantity=quantity,unit_price=price,discount_amount=discount,total_amount=total,
        is_primary_service=not command.items.filter(item_type=AutoCommandItem.Type.SERVICE).exists(),
    )
    recalculate_command(command)
    return item


@transaction.atomic
def add_product_item(*,command,product,professional=None,quantity=1,unit_price=None,discount=0):
    command=AutoCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=AutoCommand.Status.OPEN:
        raise ValidationError("Comanda não está aberta.")
    if product.tenant_id!=command.tenant_id:
        raise ValidationError("Produto pertence a outro tenant.")
    quantity=Decimal(str(quantity))
    price=Decimal(str(product.sale_price if unit_price in (None,"") else unit_price))
    discount=Decimal(str(discount or 0))
    total=(quantity*price-discount).quantize(Decimal("0.01"))
    if quantity<=0 or total<0:
        raise ValidationError("Valores inválidos.")
    item=AutoCommandItem.objects.create(
        command=command,tenant=command.tenant,item_type=AutoCommandItem.Type.PRODUCT,
        product=product,professional=professional,description=product.name,
        quantity=quantity,unit_price=price,discount_amount=discount,total_amount=total,
        cost_snapshot=product.cost_price,
    )
    recalculate_command(command)
    return item


@transaction.atomic
def register_payment(*,command,user,payment_method,amount,provider="",provider_reference=""):
    command=AutoCommand.objects.select_for_update().get(pk=command.pk)
    if command.status!=AutoCommand.Status.OPEN:
        raise ValidationError("Comanda não está aberta.")
    amount=Decimal(str(amount))
    if amount<=0:
        raise ValidationError("Valor inválido.")
    return AutoCommandPayment.objects.create(
        command=command,tenant=command.tenant,payment_method=payment_method[:20],
        amount=amount,provider=provider[:50],provider_reference=provider_reference[:190],
        received_by=user,received_at=timezone.now(),
    )
