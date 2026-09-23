import hashlib
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone

from .availability import AvailabilityService
from .models import Appointment,AppointmentRescheduleHistory,Professional


def _appointment(token,lock=False):
    qs=Appointment.objects.select_related("tenant","customer","service","professional")
    if lock:
        qs=qs.select_for_update()
    return get_object_or_404(qs,customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest())


def _caps(row):
    cfg=AvailabilityService().settings(row.tenant)
    manageable=row.status in {Appointment.Status.PENDING,Appointment.Status.CONFIRMED}
    in_time=row.starts_at>=timezone.now()+timedelta(minutes=cfg.cancel_notice_minutes)
    return {
        "can_cancel":bool(cfg.customer_can_cancel and manageable and in_time),
        "can_reschedule":bool(cfg.customer_can_reschedule and manageable and in_time),
    }


def _start(tenant,value):
    tz=ZoneInfo(tenant.timezone or "America/Recife")
    dt=datetime.fromisoformat(value)
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)


def _candidates(row):
    return Professional.objects.filter(
        tenant=row.tenant,active=True
    ).order_by("name","pk")


@transaction.atomic
def appointment_page(request,token):
    row=_appointment(token,lock=request.method=="POST")
    if request.method=="POST":
        action=request.POST.get("action")
        caps=_caps(row)
        if action=="cancel":
            if not caps["can_cancel"]:
                messages.error(request,"Este agendamento não pode mais ser cancelado online.")
            else:
                row.status=Appointment.Status.CANCELLED
                row.save(update_fields=["status","updated_at"])
                messages.success(request,"Agendamento cancelado.")
            return redirect("public-appointment-page",token=token)

        if action=="reschedule":
            if not caps["can_reschedule"]:
                messages.error(request,"Este agendamento não pode mais ser remarcado online.")
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
                        pk=int(raw),tenant=row.tenant,active=True
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
                for candidate in _candidates(row).select_for_update():
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
        "professionals":_candidates(row),
    })
