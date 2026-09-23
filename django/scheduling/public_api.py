import hashlib
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import permissions, status, throttling
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import Tenant
from .availability import AvailabilityService
from .models import (
    Appointment, AppointmentRescheduleHistory, Customer, Professional, Service,
)


class PublicBookingThrottle(throttling.AnonRateThrottle):
    rate="20/min"


def _tenant(slug):
    return Tenant.objects.filter(
        public_slug=slug,
        public_enabled=True,
        public_booking_enabled=True,
        status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],
    ).first()


def _parse_start(tenant,value):
    tz=ZoneInfo(tenant.timezone or "America/Recife")
    start=datetime.fromisoformat(str(value))
    if start.tzinfo is None:
        return start.replace(tzinfo=tz)
    return start.astimezone(tz)


def _candidate_professionals(tenant,service):
    # Keep this queryset lockable on PostgreSQL. Service eligibility is checked
    # by AvailabilityService before a candidate is exposed or selected.
    return Professional.objects.filter(
        tenant=tenant,active=True
    ).order_by("name","pk")


class PublicAvailabilityAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[PublicBookingThrottle]

    def get(self,request,slug):
        tenant=_tenant(slug)
        if not tenant:
            return Response({"detail":"Página não encontrada."},status=status.HTTP_404_NOT_FOUND)
        try:
            service_id=int(request.query_params["service_id"])
            day=date.fromisoformat(request.query_params["date"])
        except (KeyError,TypeError,ValueError):
            return Response(
                {"detail":"Informe service_id e date=YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        service=Service.objects.filter(pk=service_id,tenant=tenant,active=True).first()
        if not service:
            return Response({"detail":"Serviço não encontrado."},status=status.HTTP_404_NOT_FOUND)

        raw_professional=(request.query_params.get("professional_id") or "").strip()
        availability=AvailabilityService()
        if raw_professional:
            try:
                professional_id=int(raw_professional)
            except ValueError:
                return Response({"detail":"Profissional inválido."},status=status.HTTP_400_BAD_REQUEST)
            professional=Professional.objects.filter(
                pk=professional_id,tenant=tenant,active=True
            ).first()
            if not professional or not availability.professional_offers(
                tenant,professional.pk,service.pk
            ):
                return Response({"detail":"Profissional não oferece esse serviço."},status=status.HTTP_400_BAD_REQUEST)
            slots=availability.slots(
                tenant=tenant,service_id=service.pk,professional_id=professional.pk,
                day=day,public_rules=True,
            )
            for slot in slots:
                slot["professional_id"]=professional.pk
                slot["professional_name"]=professional.name
            return Response({
                "date":day.isoformat(),"auto_professional":False,
                "professional":{"id":professional.pk,"name":professional.name},
                "slots":slots,
            })

        combined={}
        for professional in _candidate_professionals(tenant,service):
            for slot in availability.slots(
                tenant=tenant,service_id=service.pk,professional_id=professional.pk,
                day=day,public_rules=True,
            ):
                # One row per start time. The booking endpoint rechecks and chooses
                # an available professional transactionally.
                current=combined.get(slot["value"])
                candidate={
                    **slot,
                    "professional_id":professional.pk,
                    "professional_name":professional.name,
                }
                if current is None or professional.name.lower()<current["professional_name"].lower():
                    combined[slot["value"]]=candidate
        slots=sorted(combined.values(),key=lambda item:item["value"])
        return Response({"date":day.isoformat(),"auto_professional":True,"slots":slots})


class PublicBookingAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[PublicBookingThrottle]

    @transaction.atomic
    def post(self,request,slug):
        tenant=_tenant(slug)
        if not tenant:
            return Response({"detail":"Página não encontrada."},status=status.HTTP_404_NOT_FOUND)

        data=request.data
        try:
            service=Service.objects.get(pk=int(data["service_id"]),tenant=tenant,active=True)
            starts_at=_parse_start(tenant,data["starts_at"])
        except (KeyError,TypeError,ValueError,Service.DoesNotExist):
            return Response({"detail":"Dados de agendamento inválidos."},status=status.HTTP_400_BAD_REQUEST)

        ends_at=starts_at+timedelta(minutes=service.duration_minutes)
        availability=AvailabilityService()
        requested_professional=(str(data.get("professional_id") or "")).strip()
        professional=None
        source=Appointment.Source.PUBLIC
        if requested_professional:
            try:
                professional=Professional.objects.select_for_update().get(
                    pk=int(requested_professional),tenant=tenant,active=True
                )
            except (ValueError,Professional.DoesNotExist):
                return Response({"detail":"Profissional inválido."},status=status.HTTP_400_BAD_REQUEST)
            if not availability.professional_offers(tenant,professional.pk,service.pk):
                return Response({"detail":"Profissional não oferece esse serviço."},status=status.HTTP_400_BAD_REQUEST)
            source=Appointment.Source.PROFESSIONAL_LINK if data.get("professional_link") else Appointment.Source.PUBLIC
            if not availability.is_available(
                tenant,professional,starts_at,ends_at,public_rules=True
            ):
                return Response(
                    {"detail":"Este horário não está mais disponível."},
                    status=status.HTTP_409_CONFLICT,
                )
        else:
            # Lock candidates and pick the first one that remains free.
            for candidate in _candidate_professionals(tenant,service).select_for_update():
                if not availability.professional_offers(tenant,candidate.pk,service.pk):
                    continue
                if availability.is_available(
                    tenant,candidate,starts_at,ends_at,public_rules=True
                ):
                    professional=candidate
                    break
            if not professional:
                return Response(
                    {"detail":"Não existe profissional disponível neste horário."},
                    status=status.HTTP_409_CONFLICT,
                )

        name=str(data.get("name") or "").strip()
        email=str(data.get("email") or "").strip().lower()
        phone=str(data.get("phone") or "").strip()
        if len(name)<2 or (not email and not phone):
            return Response(
                {"detail":"Informe nome e pelo menos e-mail ou telefone."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        customer=None
        if email:
            customer=Customer.objects.filter(tenant=tenant,email=email).first()
        if customer is None and phone:
            customer=Customer.objects.filter(tenant=tenant,phone=phone).first()
        if customer is None:
            customer=Customer.objects.create(
                tenant=tenant,name=name,email=email,phone=phone,active=True
            )
        else:
            changed=[]
            if name and customer.name!=name:
                customer.name=name; changed.append("name")
            if email and customer.email!=email:
                customer.email=email; changed.append("email")
            if phone and customer.phone!=phone:
                customer.phone=phone; changed.append("phone")
            if changed:
                changed.append("updated_at")
                customer.save(update_fields=changed)

        token=secrets.token_urlsafe(32)
        appointment=Appointment.objects.create(
            tenant=tenant,customer=customer,professional=professional,service=service,
            service_price_snapshot=service.price,starts_at=starts_at,ends_at=ends_at,
            status=Appointment.Status.PENDING,source=source,
            notes=str(data.get("notes") or "")[:2000],
            customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        manage_path=reverse("public-appointment-page",args=[token])
        return Response(
            {
                "id":appointment.pk,"status":appointment.status,
                "starts_at":appointment.starts_at.isoformat(),
                "professional":{"id":professional.pk,"name":professional.name},
                "manage_token":token,
                "manage_url":request.build_absolute_uri(manage_path),
            },
            status=status.HTTP_201_CREATED,
        )


class CustomerAppointmentAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[PublicBookingThrottle]

    def _appointment(self,token):
        digest=hashlib.sha256(token.encode()).hexdigest()
        return Appointment.objects.select_related(
            "tenant","customer","professional","service"
        ).filter(customer_manage_token_hash=digest).first()

    def _capabilities(self,appointment):
        schedule=AvailabilityService().settings(appointment.tenant)
        manageable=appointment.status in [Appointment.Status.PENDING,Appointment.Status.CONFIRMED]
        minimum=timezone.now()+timedelta(minutes=schedule.cancel_notice_minutes)
        in_time=appointment.starts_at>=minimum
        return {
            "can_cancel":bool(schedule.customer_can_cancel and manageable and in_time),
            "can_reschedule":bool(schedule.customer_can_reschedule and manageable and in_time),
        }

    def get(self,request,token):
        appointment=self._appointment(token)
        if not appointment:
            return Response({"detail":"Agendamento não encontrado."},status=status.HTTP_404_NOT_FOUND)
        return Response({
            "id":appointment.pk,"status":appointment.status,
            "starts_at":appointment.starts_at.isoformat(),"ends_at":appointment.ends_at.isoformat(),
            "service_id":appointment.service_id,"service":appointment.service.name,
            "professional_id":appointment.professional_id,
            "professional":appointment.professional.name if appointment.professional else None,
            **self._capabilities(appointment),
        })

    @transaction.atomic
    def patch(self,request,token):
        appointment=Appointment.objects.select_for_update().select_related(
            "tenant","service","professional"
        ).filter(customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
        if not appointment:
            return Response({"detail":"Agendamento não encontrado."},status=status.HTTP_404_NOT_FOUND)
        caps=self._capabilities(appointment)
        if not caps["can_reschedule"]:
            return Response({"detail":"Remarcação online não está disponível para este agendamento."},status=status.HTTP_403_FORBIDDEN)
        try:
            starts_at=_parse_start(appointment.tenant,request.data["starts_at"])
        except (KeyError,TypeError,ValueError):
            return Response({"detail":"Informe starts_at válido."},status=status.HTTP_400_BAD_REQUEST)
        ends_at=starts_at+timedelta(minutes=appointment.service.duration_minutes)
        availability=AvailabilityService()
        raw_prof=(str(request.data.get("professional_id") or "")).strip()
        professional=None
        if raw_prof:
            try:
                professional=Professional.objects.select_for_update().get(
                    pk=int(raw_prof),tenant=appointment.tenant,active=True
                )
            except (ValueError,Professional.DoesNotExist):
                return Response({"detail":"Profissional inválido."},status=status.HTTP_400_BAD_REQUEST)
            if not availability.professional_offers(
                appointment.tenant,professional.pk,appointment.service_id
            ):
                return Response({"detail":"Profissional não oferece esse serviço."},status=status.HTTP_400_BAD_REQUEST)
            if not availability.is_available(
                appointment.tenant,professional,starts_at,ends_at,
                exclude_appointment_id=appointment.pk,public_rules=True,
            ):
                return Response({"detail":"Horário indisponível."},status=status.HTTP_409_CONFLICT)
        else:
            for candidate in _candidate_professionals(
                appointment.tenant,appointment.service
            ).select_for_update():
                if not availability.professional_offers(
                    appointment.tenant,candidate.pk,appointment.service_id
                ):
                    continue
                if availability.is_available(
                    appointment.tenant,candidate,starts_at,ends_at,
                    exclude_appointment_id=appointment.pk,public_rules=True,
                ):
                    professional=candidate
                    break
            if not professional:
                return Response({"detail":"Nenhum profissional disponível."},status=status.HTTP_409_CONFLICT)

        old_professional=appointment.professional
        old_start=appointment.starts_at
        old_end=appointment.ends_at
        appointment.professional=professional
        appointment.starts_at=starts_at
        appointment.ends_at=ends_at
        appointment.save(update_fields=["professional","starts_at","ends_at","updated_at"])
        AppointmentRescheduleHistory.objects.create(
            tenant=appointment.tenant,appointment=appointment,
            old_professional=old_professional,new_professional=professional,
            old_starts_at=old_start,old_ends_at=old_end,
            new_starts_at=starts_at,new_ends_at=ends_at,
            reason=str(request.data.get("reason") or "Remarcação pelo cliente")[:255],
            actor_type=AppointmentRescheduleHistory.ActorType.CUSTOMER,
        )
        return Response({
            "id":appointment.pk,"status":appointment.status,
            "starts_at":appointment.starts_at.isoformat(),"ends_at":appointment.ends_at.isoformat(),
            "professional_id":professional.pk,"professional":professional.name,
            **self._capabilities(appointment),
        })

    @transaction.atomic
    def delete(self,request,token):
        appointment=Appointment.objects.select_for_update().select_related("tenant").filter(
            customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest()
        ).first()
        if not appointment:
            return Response({"detail":"Agendamento não encontrado."},status=status.HTTP_404_NOT_FOUND)
        if not self._capabilities(appointment)["can_cancel"]:
            return Response(
                {"detail":"Cancelamento online não está disponível para este agendamento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        appointment.status=Appointment.Status.CANCELLED
        appointment.save(update_fields=["status","updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
