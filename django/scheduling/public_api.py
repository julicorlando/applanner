import hashlib
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, throttling
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import Tenant
from .availability import AvailabilityService
from .models import Appointment, Customer, Professional, Service


class PublicBookingThrottle(throttling.AnonRateThrottle):
    rate="20/min"


def _tenant(slug):
    return Tenant.objects.filter(
        public_slug=slug,
        public_enabled=True,
        public_booking_enabled=True,
        status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],
    ).first()


class PublicAvailabilityAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[PublicBookingThrottle]

    def get(self,request,slug):
        tenant=_tenant(slug)
        if not tenant:
            return Response({"detail":"Página não encontrada."},status=status.HTTP_404_NOT_FOUND)
        try:
            service_id=int(request.query_params["service_id"])
            professional_id=int(request.query_params["professional_id"])
            day=date.fromisoformat(request.query_params["date"])
        except (KeyError,TypeError,ValueError):
            return Response(
                {"detail":"Informe service_id, professional_id e date=YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        slots=AvailabilityService().slots(
            tenant=tenant,
            service_id=service_id,
            professional_id=professional_id,
            day=day,
            public_rules=True,
        )
        return Response({"date":day.isoformat(),"slots":slots})


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
            professional=Professional.objects.select_for_update().get(
                pk=int(data["professional_id"]),tenant=tenant,active=True
            )
            tz=ZoneInfo(tenant.timezone or "America/Recife")
            starts_at=datetime.fromisoformat(str(data["starts_at"]))
            if starts_at.tzinfo is None:
                starts_at=starts_at.replace(tzinfo=tz)
            else:
                starts_at=starts_at.astimezone(tz)
        except (KeyError,TypeError,ValueError,Service.DoesNotExist,Professional.DoesNotExist):
            return Response({"detail":"Dados de agendamento inválidos."},status=status.HTTP_400_BAD_REQUEST)

        if not AvailabilityService().professional_offers(tenant,professional.pk,service.pk):
            return Response({"detail":"Profissional não oferece esse serviço."},status=status.HTTP_400_BAD_REQUEST)

        ends_at=starts_at+timedelta(minutes=service.duration_minutes)
        if not AvailabilityService().is_available(
            tenant,professional,starts_at,ends_at,public_rules=True
        ):
            return Response(
                {"detail":"Este horário não está mais disponível."},
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
            tenant=tenant,
            customer=customer,
            professional=professional,
            service=service,
            service_price_snapshot=service.price,
            starts_at=starts_at,
            ends_at=ends_at,
            status=Appointment.Status.PENDING,
            source=Appointment.Source.PUBLIC,
            notes=str(data.get("notes") or "")[:2000],
            customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        )
        return Response(
            {
                "id":appointment.pk,
                "status":appointment.status,
                "starts_at":appointment.starts_at.isoformat(),
                "manage_token":token,
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

    def get(self,request,token):
        appointment=self._appointment(token)
        if not appointment:
            return Response({"detail":"Agendamento não encontrado."},status=status.HTTP_404_NOT_FOUND)
        return Response({
            "id":appointment.pk,
            "status":appointment.status,
            "starts_at":appointment.starts_at.isoformat(),
            "ends_at":appointment.ends_at.isoformat(),
            "service":appointment.service.name,
            "professional":appointment.professional.name if appointment.professional else None,
            "can_cancel":appointment.status in [Appointment.Status.PENDING,Appointment.Status.CONFIRMED],
        })

    @transaction.atomic
    def delete(self,request,token):
        appointment=Appointment.objects.select_for_update().select_related("tenant").filter(
            customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest()
        ).first()
        if not appointment:
            return Response({"detail":"Agendamento não encontrado."},status=status.HTTP_404_NOT_FOUND)

        settings_obj=AvailabilityService().settings(appointment.tenant)
        if not settings_obj.customer_can_cancel:
            return Response({"detail":"Cancelamento online não está disponível."},status=status.HTTP_403_FORBIDDEN)
        if appointment.status not in [Appointment.Status.PENDING,Appointment.Status.CONFIRMED]:
            return Response({"detail":"Este agendamento não pode mais ser cancelado."},status=status.HTTP_409_CONFLICT)

        minimum=timezone.now()+timedelta(minutes=settings_obj.cancel_notice_minutes)
        if appointment.starts_at<minimum:
            return Response(
                {"detail":"O prazo para cancelamento online foi encerrado."},
                status=status.HTTP_409_CONFLICT,
            )

        appointment.status=Appointment.Status.CANCELLED
        appointment.save(update_fields=["status","updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
