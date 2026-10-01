"""Reserva pública de quadras, separada dos agendamentos de profissionais."""

import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import number_format
from requests.exceptions import RequestException
from rest_framework import permissions, status, throttling
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.payment_services import create_tenant_pix, has_connected_tenant_gateway
from billing.segment_access import segment_enabled
from tenants.models import Tenant

from .models import Court, Reservation, SportsSettings
from .services import ArenaReservationService


def _public_tenant(slug):
    tenant=Tenant.objects.filter(
        Q(public_slug=slug)|Q(public_slug__isnull=True,slug=slug),
        status__in=[Tenant.Status.ACTIVE,Tenant.Status.TRIAL],
        public_enabled=True,public_booking_enabled=True,deleted_at__isnull=True,
    ).first()
    return tenant if tenant and segment_enabled(tenant,"arena") else None


def _deposit_available(tenant):
    from scheduling.models import TenantScheduleSettings
    settings=ArenaReservationService().sports_settings(tenant)
    schedule=TenantScheduleSettings.objects.filter(tenant=tenant).first()
    return bool(settings.require_deposit and settings.deposit_value>0 and schedule
                and schedule.online_booking_payments_enabled and has_connected_tenant_gateway(tenant))


class ArenaPublicThrottle(throttling.AnonRateThrottle):
    scope="arena_public"
    rate="20/min"


class CourtSlotsAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[ArenaPublicThrottle]

    def get(self,request,slug):
        tenant=_public_tenant(slug)
        if not tenant:
            return Response({"detail":"Arena indisponível."},status=404)
        try:
            court=Court.objects.get(pk=int(request.query_params["court_id"]),tenant=tenant,active=True)
            day=date.fromisoformat(request.query_params["date"])
            duration=int(request.query_params.get("duration") or court.minimum_minutes)
        except (KeyError,TypeError,ValueError,Court.DoesNotExist):
            return Response({"detail":"Quadra, data ou duração inválida."},status=400)
        if duration<court.minimum_minutes or duration>court.maximum_minutes:
            return Response({"detail":"Duração indisponível para esta quadra."},status=400)
        settings=ArenaReservationService().sports_settings(tenant)
        local_today=timezone.now().astimezone(ZoneInfo(tenant.timezone or "America/Recife")).date()
        if day<local_today or day>local_today+timedelta(days=settings.maximum_days_ahead):
            return Response({"detail":"Data fora do período permitido."},status=400)
        slots=ArenaReservationService().slots(tenant,court,day,duration)
        return Response({"slots":[{
            "value":item["value"],"label":f'{item["label"]} · R$ {number_format(item["total"], decimal_pos=2, use_l10n=True)}',"ends_at":item["ends_at"],
            "total":str(item["total"]),
        } for item in slots]})


class CourtBookingAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[ArenaPublicThrottle]

    def post(self,request,slug):
        tenant=_public_tenant(slug)
        if not tenant:
            return Response({"detail":"Arena indisponível."},status=404)
        try:
            court=Court.objects.get(pk=int(request.data["court_id"]),tenant=tenant,active=True)
            start=datetime.fromisoformat(str(request.data["starts_at"]))
            duration=int(request.data.get("duration") or court.minimum_minutes)
        except (KeyError,TypeError,ValueError,Court.DoesNotExist):
            return Response({"detail":"Quadra, horário ou duração inválidos."},status=400)
        tenant_tz=ZoneInfo(tenant.timezone or "America/Recife")
        start=start.replace(tzinfo=tenant_tz) if start.tzinfo is None else start.astimezone(tenant_tz)
        if duration<court.minimum_minutes or duration>court.maximum_minutes:
            return Response({"detail":"Duração indisponível para esta quadra."},status=400)
        name=str(request.data.get("name") or "").strip()
        phone=str(request.data.get("phone") or "").strip()
        email=str(request.data.get("email") or "").strip().lower()
        payment=str(request.data.get("payment") or "onsite")
        from scheduling.customer_identity import contact_values,resolve_customer
        try:
            name,phone,email=contact_values(name,phone,email)
        except ValidationError as exc:
            return Response({"detail":" ".join(exc.messages)},status=400)
        if payment not in {"onsite","pix"} or (payment=="pix" and (not _deposit_available(tenant) or "@" not in email)):
            return Response({"detail":"Pagamento antecipado indisponível. Escolha pagar na unidade."},status=400)
        service=ArenaReservationService()
        try:
            with transaction.atomic():
                customer,reused=resolve_customer(tenant,name,phone,email)
                reservation,token=service.create_reservation(
                    tenant=tenant,court=court,start=start,end=start+timedelta(minutes=duration),
                    customer=customer,customer_name=name,customer_phone=phone,customer_email=email,
                    payment_method=payment,notes=str(request.data.get("notes") or ""),
                )
        except ValidationError as exc:
            return Response({"detail":" ".join(exc.messages)},status=409)
        if payment=="pix":
            try:
                create_tenant_pix(tenant=tenant,reference_type="reservation",reference_id=reservation.pk,
                    amount=reservation.deposit_amount,payer_email=email,expiration_minutes=60)
            except (ValueError,RuntimeError,RequestException):
                reservation.status=Reservation.Status.CANCELLED
                reservation.cancelled_at=timezone.now()
                reservation.save(update_fields=["status","cancelled_at","updated_at"])
                return Response({"detail":"Não foi possível gerar o Pix. Escolha outro horário ou tente novamente."},status=502)
        return Response({
            "detail":"Reserva confirmada." if payment=="onsite" else "Reserva aguardando confirmação do Pix.",
            "court":court.name,"starts_at":reservation.starts_at.isoformat(),
            "ends_at":reservation.ends_at.isoformat(),"total":str(reservation.total_amount),
            "timezone":tenant.timezone or "America/Recife",
            "customer_reused":reused,
            "manage_url":f"/arena/reserva/{token}/",
        },status=status.HTTP_201_CREATED)


def court_reservation_page(request,token):
    reservation=get_object_or_404(Reservation.objects.select_related("court","tenant"),
        manage_token_hash=hashlib.sha256(token.encode()).hexdigest())
    cancel_reason=""
    if reservation.status!=Reservation.Status.CONFIRMED:
        cancel_reason=f"Não é possível cancelar online: a reserva está {reservation.get_status_display().lower()}."
    elif reservation.payment_method!="onsite":
        cancel_reason="Reservas com pagamento antecipado precisam ser canceladas com a arena para tratar o pagamento."
    elif reservation.starts_at<=timezone.now():
        cancel_reason="O horário desta reserva já começou; o cancelamento online não está disponível."
    if request.method=="POST" and request.POST.get("action")=="cancel":
        if reservation.status!=Reservation.Status.CONFIRMED or reservation.payment_method!="onsite":
            messages.error(request,"Esta reserva não pode ser cancelada online. Contate a arena.")
        elif reservation.starts_at<=timezone.now():
            messages.error(request,"O horário desta reserva já começou.")
        else:
            reservation.status=Reservation.Status.CANCELLED
            reservation.cancelled_at=timezone.now()
            reservation.save(update_fields=["status","cancelled_at","updated_at"])
            messages.success(request,"Reserva cancelada e horário liberado.")
        return redirect("public-arena-reservation",token=token)
    payment=reservation.tenant.payment_transactions.filter(reference_type="reservation",
        reference_id=reservation.pk,method="pix").order_by("-created_at").first()
    return render(request,"arena/public_reservation.html",{"reservation":reservation,
        "payment":payment,"token":token,"cancel_reason":cancel_reason})
