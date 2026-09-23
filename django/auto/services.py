from datetime import timedelta
from decimal import Decimal
import hashlib
import secrets

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.crypto import decrypt_text, encrypt_text

from finance.models import FinancialTransaction, Product, ProductStockMovement, ProfessionalCommission
from scheduling.models import Appointment

from .models import (
    AutoCommand, AutoCommandItem, AutoCommandPayment, AutoSettings, CRMEvent, DeliveryTerm,
    Estimate, EstimateItem, Job, JobMaterialUsage, JobStatusHistory, JobStep,
    VehicleMaintenance, VehicleProfile,
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


def _estimate_total(estimate):
    subtotal=sum((item.total_amount for item in estimate.items.all()),Decimal("0"))
    total=max(Decimal("0"),subtotal-estimate.discount_amount)
    Estimate.objects.filter(pk=estimate.pk).update(
        subtotal=subtotal,total_amount=total,updated_at=timezone.now()
    )
    estimate.subtotal=subtotal
    estimate.total_amount=total
    return estimate


@transaction.atomic
def create_estimate(*,job,user,expires_at=None,discount_amount=0):
    token=secrets.token_urlsafe(32)
    estimate=Estimate.objects.create(
        tenant=job.tenant,job=job,
        public_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        public_token_encrypted=encrypt_text(token),
        expires_at=expires_at,discount_amount=Decimal(str(discount_amount or 0)),
        created_by=user,
    )
    return estimate,token


@transaction.atomic
def add_estimate_item(*,estimate,service=None,product=None,description="",quantity=1,unit_price=None):
    estimate=Estimate.objects.select_for_update().get(pk=estimate.pk)
    if estimate.status!=Estimate.Status.DRAFT:
        raise ValidationError("Somente orçamentos em rascunho podem ser alterados.")
    if service and service.tenant_id!=estimate.tenant_id:
        raise ValidationError("Serviço pertence a outra empresa.")
    if product and product.tenant_id!=estimate.tenant_id:
        raise ValidationError("Produto pertence a outra empresa.")
    quantity=Decimal(str(quantity))
    if quantity<=0:
        raise ValidationError("Quantidade inválida.")
    if unit_price in (None,""):
        if service:
            unit_price=service.price
        elif product:
            unit_price=product.sale_price
        else:
            raise ValidationError("Informe o valor do item.")
    price=Decimal(str(unit_price)).quantize(Decimal("0.01"))
    if price<0:
        raise ValidationError("Valor inválido.")
    label=(description or (service.name if service else product.name if product else "")).strip()
    if not label:
        raise ValidationError("Informe a descrição do item.")
    item=EstimateItem.objects.create(
        estimate=estimate,tenant=estimate.tenant,service=service,product=product,
        description=label[:190],quantity=quantity,unit_price=price,
        total_amount=(quantity*price).quantize(Decimal("0.01")),
    )
    _estimate_total(estimate)
    return item


@transaction.atomic
def send_estimate(*,estimate):
    estimate=Estimate.objects.select_for_update().get(pk=estimate.pk)
    if not estimate.items.exists():
        raise ValidationError("Adicione ao menos um item antes de enviar.")
    if estimate.status not in {Estimate.Status.DRAFT,Estimate.Status.SENT}:
        raise ValidationError("Este orçamento não pode ser enviado.")
    _estimate_total(estimate)
    estimate.status=Estimate.Status.SENT
    estimate.sent_at=timezone.now()
    estimate.save(update_fields=["status","sent_at","updated_at"])
    return estimate


def estimate_token(estimate):
    return decrypt_text(estimate.public_token_encrypted)


@transaction.atomic
def respond_estimate(*,token,approved,customer_note=""):
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    estimate=Estimate.objects.select_for_update().select_related("job").get(public_token_hash=token_hash)
    if estimate.expires_at and estimate.expires_at<=timezone.now():
        estimate.status=Estimate.Status.EXPIRED
        estimate.save(update_fields=["status","updated_at"])
        raise ValidationError("Este orçamento expirou.")
    if estimate.status==Estimate.Status.APPROVED:
        return estimate
    if estimate.status not in {Estimate.Status.SENT,Estimate.Status.DRAFT}:
        raise ValidationError("Este orçamento não aceita mais resposta.")
    estimate.status=Estimate.Status.APPROVED if approved else Estimate.Status.REJECTED
    estimate.customer_note=(customer_note or "")[:500]
    estimate.responded_at=timezone.now()
    estimate.save(update_fields=["status","customer_note","responded_at","updated_at"])
    if approved:
        command=open_command(job=estimate.job,user=None)
        for item in estimate.items.select_related("service","product").all():
            if command.items.filter(approved_estimate=estimate,description=item.description).exists():
                continue
            item_type=AutoCommandItem.Type.SERVICE if item.service_id else (
                AutoCommandItem.Type.PRODUCT if item.product_id else AutoCommandItem.Type.MANUAL
            )
            AutoCommandItem.objects.create(
                command=command,tenant=estimate.tenant,item_type=item_type,
                service=item.service,product=item.product,description=item.description,
                quantity=item.quantity,unit_price=item.unit_price,total_amount=item.total_amount,
                cost_snapshot=item.product.cost_price if item.product_id else None,
                approved_estimate=estimate,
            )
        recalculate_command(command)
    return estimate


@transaction.atomic
def update_job_step(*,step,status,professional=None,notes=""):
    step=JobStep.objects.select_for_update().get(pk=step.pk)
    valid={value for value,_ in JobStep.Status.choices}
    if status not in valid:
        raise ValidationError("Status de etapa inválido.")
    now=timezone.now()
    if status==JobStep.Status.IN_PROGRESS and not step.started_at:
        step.started_at=now
    if status==JobStep.Status.COMPLETED:
        step.started_at=step.started_at or now
        step.completed_at=now
    elif status==JobStep.Status.PENDING:
        step.started_at=None
        step.completed_at=None
    elif status==JobStep.Status.SKIPPED:
        step.completed_at=now
    step.status=status
    step.professional=professional
    step.notes=(notes or "")[:500]
    step.save()
    return step


@transaction.atomic
def create_delivery_term(*,job):
    existing=DeliveryTerm.objects.filter(job=job).first()
    if existing:
        return existing,decrypt_text(existing.public_token_encrypted)
    settings_obj,_=AutoSettings.objects.get_or_create(tenant=job.tenant)
    token=secrets.token_urlsafe(32)
    row=DeliveryTerm.objects.create(
        tenant=job.tenant,job=job,
        public_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        public_token_encrypted=encrypt_text(token),
        terms_snapshot=settings_obj.terms_text or (
            "Declaro que recebi o veículo e conferi os serviços realizados."
        ),
    )
    return row,token


def delivery_token(term):
    return decrypt_text(term.public_token_encrypted)


@transaction.atomic
def accept_delivery_term(*,token,name,ip=None):
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    row=DeliveryTerm.objects.select_for_update().select_related("job").get(public_token_hash=token_hash)
    if row.accepted_at:
        return row
    if not (name or "").strip():
        raise ValidationError("Informe o nome de quem está aceitando a entrega.")
    row.accepted_name=name.strip()[:150]
    row.accepted_ip=ip or None
    row.accepted_at=timezone.now()
    row.save(update_fields=["accepted_name","accepted_ip","accepted_at"])
    return row
