import hashlib
from datetime import datetime,timedelta
from requests.exceptions import RequestException
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.signing import dumps
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone

from .availability import AvailabilityService
from .models import Appointment,AppointmentRescheduleHistory,Professional


def _appointment(token,lock=False):
    qs=Appointment.objects.select_related("tenant","customer","service").prefetch_related("product_reservations__product")
    if lock:
        qs=qs.select_for_update()
    return get_object_or_404(qs,customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest())


def _caps(row):
    cfg=AvailabilityService().settings(row.tenant,unit=row.unit)
    manageable=row.status in {Appointment.Status.PENDING,Appointment.Status.CONFIRMED}
    in_time=row.starts_at>=timezone.now()+timedelta(minutes=cfg.cancel_notice_minutes)
    def reason(enabled, action):
        if not manageable:
            return f"Não é possível {action}: o agendamento está {row.get_status_display().lower()}."
        if not enabled:
            return f"O estabelecimento não permite {action} online."
        if row.starts_at<=timezone.now():
            return f"Não é possível {action} online: o horário do agendamento já começou."
        if not in_time:
            return (f"Para {action} online, é necessário avisar com pelo menos "
                    f"{cfg.cancel_notice_minutes} minutos de antecedência. O prazo desta reserva já encerrou.")
        return ""
    return {
        "can_cancel":bool(cfg.customer_can_cancel and manageable and in_time),
        "can_reschedule":bool(cfg.customer_can_reschedule and manageable and in_time),
        "cancel_reason":reason(cfg.customer_can_cancel,"cancelar"),
        "reschedule_reason":reason(cfg.customer_can_reschedule,"reagendar"),
    }


def _start(tenant,value):
    tz=ZoneInfo(tenant.timezone or "America/Recife")
    dt=datetime.fromisoformat(value)
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def _candidates(row):
    availability=AvailabilityService()
    return [professional for professional in Professional.objects.filter(
        tenant=row.tenant,unit=row.unit,active=True
    ).order_by("name","pk") if availability.professional_offers(row.tenant,professional.pk,row.service_id)]


@transaction.atomic
def appointment_page(request,token):
    row=_appointment(token,lock=request.method=="POST")
    from billing.models import TenantPaymentTransaction
    from billing.payment_services import has_connected_tenant_gateway
    amount=row.booking_payment_amount or (row.service_price_snapshot if row.service_price_snapshot is not None else row.service.price)
    payments=TenantPaymentTransaction.objects.filter(tenant=row.tenant,reference_type="appointment",
        reference_id=row.pk).order_by("-created_at")
    payment=payments.first()
    payment_connected=has_connected_tenant_gateway(row.tenant)
    payment_reason=""
    if row.status not in {Appointment.Status.PENDING,Appointment.Status.CONFIRMED}:
        payment_reason=f"O pagamento online não está disponível: o agendamento está {row.get_status_display().lower()}."
    elif not payment_connected:
        payment_reason="O estabelecimento ainda não habilitou o recebimento online."
    elif not row.customer.email:
        payment_reason="Para gerar o Pix, é necessário um e-mail no cadastro do cliente. Solicite a atualização ao estabelecimento."
    if request.method=="POST":
        action=request.POST.get("action")
        if action=="pay":
            if (row.booking_payment==Appointment.BookingPayment.ON_SITE or row.status not in
                {Appointment.Status.PENDING,Appointment.Status.CONFIRMED} or not row.customer.email or not has_connected_tenant_gateway(row.tenant)):
                messages.error(request,"O pagamento online não está disponível para este agendamento.")
            elif payment and payment.status==TenantPaymentTransaction.Status.PAID:
                messages.info(request,"Este pagamento já foi confirmado.")
            else:
                from billing.payment_services import create_tenant_pix
                try:
                    create_tenant_pix(tenant=row.tenant,reference_type="appointment",reference_id=row.pk,
                        amount=amount,payer_email=row.customer.email,expiration_minutes=60)
                except (ValueError,RuntimeError,RequestException):
                    messages.error(request,"Não foi possível gerar o Pix. Confira os dados de pagamento da empresa e tente novamente.")
                else:
                    messages.success(request,"Pix gerado. Copie o código e aguarde a confirmação do pagamento.")
            return redirect("public-appointment-page",token=token)
        caps=_caps(row)
        if action=="cancel":
            if not caps["can_cancel"]:
                messages.error(request,caps["cancel_reason"])
            else:
                row.status=Appointment.Status.CANCELLED
                row.save(update_fields=["status","updated_at"])
                messages.success(request,"Agendamento cancelado.")
            return redirect("public-appointment-page",token=token)

        if action=="reschedule":
            if not caps["can_reschedule"]:
                messages.error(request,caps["reschedule_reason"])
                return redirect("public-appointment-page",token=token)
            try:
                starts_at=_start(row.tenant,request.POST["starts_at"])
            except (KeyError,TypeError,ValueError):
                messages.error(request,"Escolha uma nova data e horário válidos.")
                return redirect("public-appointment-page",token=token)
            ends_at=starts_at+timedelta(minutes=row.service.duration_minutes)
            availability=AvailabilityService()
            professional=None
            raw=(request.POST.get("professional_id") or "").strip()
            if raw:
                try:
                    candidate=Professional.objects.select_for_update().get(
                        pk=int(raw),tenant=row.tenant,unit=row.unit,active=True
                    )
                except (ValueError,Professional.DoesNotExist):
                    candidate=None
                if candidate and availability.professional_offers(
                    row.tenant,candidate.pk,row.service_id
                ) and availability.is_available(
                    row.tenant,candidate,starts_at,ends_at,
                    exclude_appointment_id=row.pk,public_rules=True,
                ):
                    professional=candidate
            else:
                candidate_ids=[candidate.pk for candidate in _candidates(row)]
                for candidate in Professional.objects.select_for_update().filter(
                    tenant=row.tenant,active=True,pk__in=candidate_ids
                ).order_by("name","pk"):
                    if not availability.professional_offers(
                        row.tenant,candidate.pk,row.service_id
                    ):
                        continue
                    if availability.is_available(
                        row.tenant,candidate,starts_at,ends_at,
                        exclude_appointment_id=row.pk,public_rules=True,
                    ):
                        professional=candidate
                        break
            if professional is None:
                messages.error(request,"O horário escolhido não está mais disponível.")
                return redirect("public-appointment-page",token=token)

            old_prof=row.professional
            old_start=row.starts_at
            old_end=row.ends_at
            row.professional=professional
            row.starts_at=starts_at
            row.ends_at=ends_at
            row.save(update_fields=["professional","starts_at","ends_at","updated_at"])
            AppointmentRescheduleHistory.objects.create(
                tenant=row.tenant,appointment=row,old_professional=old_prof,
                new_professional=professional,old_starts_at=old_start,old_ends_at=old_end,
                new_starts_at=starts_at,new_ends_at=ends_at,
                reason="Remarcação pelo cliente",
                actor_type=AppointmentRescheduleHistory.ActorType.CUSTOMER,
            )
            messages.success(request,"Agendamento remarcado.")
            return redirect("public-appointment-page",token=token)

    return render(request,"scheduling/public_appointment.html",{
        "appointment":row,"token":token,"capabilities":_caps(row),
        "payment":payment,"payment_amount":amount,"payment_connected":payment_connected,
        "can_pay":not payment_reason,"payment_reason":payment_reason,
        "professionals":_candidates(row),
        "rating_token":dumps({"appointment":row.pk},salt="appointment-rating")
            if row.status==Appointment.Status.COMPLETED else None,
    })
