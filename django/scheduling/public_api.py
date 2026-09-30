import hashlib
import secrets
import re
from decimal import Decimal
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from core.crypto import encrypt_text

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


class PublicWaitlistAPIView(APIView):
    permission_classes=[permissions.AllowAny]
    throttle_classes=[PublicBookingThrottle]

    @transaction.atomic
    def post(self,request,slug):
        from engagement.models import WaitlistEntry
        from billing.segment_access import require_feature
        from django.core.exceptions import PermissionDenied
        tenant=_tenant(slug)
        if not tenant:
            return Response({"detail":"Página não encontrada."},status=404)
        try:
            require_feature(tenant,"waitlist")
        except PermissionDenied:
            return Response({"detail":"A lista de espera não está disponível neste plano."},status=403)
        try:
            service=Service.objects.get(tenant=tenant,pk=int(request.data["service_id"]),active=True)
            day=date.fromisoformat(str(request.data["date"]))
            professional_id=str(request.data.get("professional_id") or "").strip()
            professional=(Professional.objects.get(tenant=tenant,pk=int(professional_id),active=True)
                          if professional_id else None)
        except (KeyError,ValueError,TypeError,Service.DoesNotExist,Professional.DoesNotExist):
            return Response({"detail":"Serviço, profissional ou data inválidos."},status=400)
        if day<timezone.localdate() or day>timezone.localdate()+timedelta(days=90):
            return Response({"detail":"Escolha uma data entre hoje e os próximos 90 dias."},status=400)
        availability=AvailabilityService()
        candidates=[professional] if professional else _candidate_professionals(tenant,service)
        if any(availability.professional_offers(tenant,item.pk,service.pk) and availability.slots(
            tenant=tenant,service_id=service.pk,professional_id=item.pk,day=day,public_rules=True,
        ) for item in candidates):
            return Response({"detail":"Ainda há horários disponíveis nesta data. Escolha um horário para agendar."},status=409)
        name=str(request.data.get("name") or "").strip()[:150]
        phone=str(request.data.get("phone") or "").strip()[:32]
        email=str(request.data.get("email") or "").strip().lower()[:254]
        if len(name)<2 or not (phone or email):
            return Response({"detail":"Informe nome e pelo menos telefone ou e-mail."},status=400)
        # Lock tenant so concurrent submissions cannot create duplicate waiting entries.
        Tenant.objects.select_for_update().get(pk=tenant.pk)
        customer=(Customer.objects.filter(tenant=tenant,email=email).first() if email else None)
        if not customer and phone:
            customer=Customer.objects.filter(tenant=tenant,phone=phone).first()
        if not customer:
            customer=Customer.objects.create(tenant=tenant,name=name,email=email,phone=phone)
        entry,created=WaitlistEntry.objects.get_or_create(tenant=tenant,customer=customer,service=service,
            professional=professional,preferred_date=day,status=WaitlistEntry.Status.WAITING)
        return Response({"detail":"Você entrou na lista de espera. O estabelecimento entrará em contato se surgir um horário.",
            "id":entry.pk},status=201 if created else 200)


def _tenant(slug):
    from django.db.models import Q
    return Tenant.objects.filter(
        Q(public_slug=slug)|Q(public_slug__isnull=True,slug=slug),
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

        config=availability.settings(tenant)
        payment_choice=str(data.get("payment_choice") or Appointment.BookingPayment.ON_SITE)
        allowed={
            Appointment.BookingPayment.ON_SITE:config.allow_pay_on_site,
            Appointment.BookingPayment.PARTIAL:config.allow_partial_payment,
            Appointment.BookingPayment.FULL:config.allow_full_payment,
        }
        if not allowed.get(payment_choice):
            return Response({"detail":"A forma de pagamento escolhida não está disponível."},status=400)
        if payment_choice!=Appointment.BookingPayment.ON_SITE:
            from billing.payment_services import has_connected_tenant_gateway
            if not email or not config.online_booking_payments_enabled or not has_connected_tenant_gateway(tenant):
                return Response({"detail":"Para pagar por Pix, informe seu e-mail e a empresa deve conectar o Mercado Pago."},status=400)
            if payment_choice==Appointment.BookingPayment.PARTIAL and not 1<=config.deposit_percent<=99:
                return Response({"detail":"O percentual de sinal da empresa deve estar entre 1 e 99."},status=400)
        payment_amount=(service.price*Decimal(config.deposit_percent)/Decimal("100")).quantize(Decimal("0.01")) if payment_choice==Appointment.BookingPayment.PARTIAL else service.price
        if payment_choice!=Appointment.BookingPayment.ON_SITE and payment_amount<Decimal("0.01"):
            return Response({"detail":"O valor do Pix deve ser maior que zero."},status=400)

        from billing.segment_access import segment_enabled
        vehicle_plate=""
        vehicle_model=""
        if segment_enabled(tenant,"auto"):
            vehicle_plate=re.sub(r"[^A-Z0-9]","",str(data.get("vehicle_plate") or "").upper())
            vehicle_model=str(data.get("vehicle_model") or "").strip()[:100]
            if not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}",vehicle_plate) or not vehicle_model:
                return Response({"detail":"Informe placa e modelo válidos do veículo."},status=400)

        customer=None
        if email:
            customer=Customer.objects.filter(tenant=tenant,email=email).first()
        if customer is None and phone:
            customer=Customer.objects.filter(tenant=tenant,phone=phone).first()
        vehicle=None
        if vehicle_plate:
            from auto.models import Vehicle
            vehicle=Vehicle.objects.select_for_update().filter(tenant=tenant,plate=vehicle_plate).first()
            if vehicle and (customer is None or vehicle.customer_id!=customer.pk):
                return Response({"detail":"Esta placa já está vinculada a outro cliente. Procure o estabelecimento."},status=409)
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

        if vehicle_plate:
            if vehicle is None:
                vehicle=Vehicle.objects.create(tenant=tenant,customer=customer,plate=vehicle_plate,model=vehicle_model)

        token=secrets.token_urlsafe(32)
        appointment=Appointment.objects.create(
            tenant=tenant,customer=customer,professional=professional,service=service,
            vehicle=vehicle,
            service_price_snapshot=service.price,starts_at=starts_at,ends_at=ends_at,
            status=Appointment.Status.CONFIRMED,source=source,
            booking_payment=payment_choice,
            booking_payment_amount=payment_amount if payment_choice!=Appointment.BookingPayment.ON_SITE else None,
            notes=str(data.get("notes") or "")[:2000],
            customer_manage_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            customer_manage_token_encrypted=encrypt_text(token),
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
