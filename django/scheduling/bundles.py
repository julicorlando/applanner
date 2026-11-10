"""Multi-service reservations reuse the canonical booking path in one transaction."""

import hashlib
import json
import secrets
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import render
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from tenants.models import Unit
from .availability import AvailabilityService
from .models import Appointment, AppointmentBundle, Professional, Service
from .public_api import (
    PublicBookingAPIView,
    PublicBookingThrottle,
    _tenant,
    _selected_unit,
    _parse_start,
    _booking_response,
)


def data_items(tenant, unit, data):
    raw = data.get("items")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
        raise ValidationError("Escolha de um a cinco serviços.")
    result = []
    for row in raw:
        try:
            service = Service.objects.get(
                pk=int(row["service_id"]), tenant=tenant, active=True
            )
            professional_id = (
                int(row["professional_id"]) if row.get("professional_id") else None
            )
            if service.unit_id not in (None, unit.pk):
                raise ValueError
        except (KeyError, ValueError, TypeError, Service.DoesNotExist):
            raise ValidationError("Serviço ou profissional inválido.") from None
        result.append((service, professional_id))
    return result


def plan_sequence(tenant, unit, items, start):
    engine = AvailabilityService()
    settings = engine.settings(tenant, unit)
    plan = []
    cursor = start
    professionals = list(
        Professional.objects.filter(tenant=tenant, unit=unit, active=True).order_by(
            "pk"
        )
    )
    for service, requested in items:
        end = cursor + timedelta(minutes=service.duration_minutes)
        candidates = [
            row for row in professionals if not requested or row.pk == requested
        ]
        professional = next(
            (
                row
                for row in candidates
                if engine.professional_offers(tenant, row.pk, service.pk)
                and engine.is_available(tenant, row, cursor, end, public_rules=True, service=service)
            ),
            None,
        )
        if not professional:
            raise ValidationError(
                "A sequência completa não está disponível nesse horário. Escolha outro início ou profissional."
            )
        plan.append(
            {
                "service": service,
                "professional": professional,
                "starts_at": cursor,
                "ends_at": end,
            }
        )
        cursor = end + timedelta(minutes=settings.buffer_minutes)
    return plan


def serialize_plan(plan):
    return [
        {
            "service_id": row["service"].pk,
            "service": row["service"].name,
            "professional_id": row["professional"].pk,
            "professional": row["professional"].name,
            "starts_at": row["starts_at"].isoformat(),
            "ends_at": row["ends_at"].isoformat(),
            "price": str(row["service"].price),
        }
        for row in plan
    ]


class DelegatedRequest:
    def __init__(self, request, data, key):
        self.original = request
        self.data = data
        self.headers = dict(request.headers)
        self.headers["Idempotency-Key"] = key

    def __getattr__(self, key):
        return getattr(self.original, key)


class BundleAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PublicBookingThrottle]

    def post(self, request, slug):
        tenant = _tenant(slug)
        if not tenant or tenant.deleted_at or tenant.archived_at:
            return Response({"detail": "Estabelecimento indisponível."}, status=404)
        from billing.segment_access import segment_enabled

        if segment_enabled(tenant, "arena") or segment_enabled(tenant, "auto"):
            return Response(
                {"detail": "Use o fluxo específico deste segmento."}, status=400
            )
        data = request.data
        if not isinstance(data, dict):
            return Response({"detail": "Dados da reserva inválidos."}, status=400)
        try:
            unit = _selected_unit(tenant, data.get("unit_id"))
            if not unit or str(unit.pk) != str(data.get("unit_id")):
                raise ValidationError("Escolha uma unidade válida.")
            items = data_items(tenant, unit, data)
            start = _parse_start(tenant, data.get("starts_at", ""))
            if data.get("preview"):
                plan = plan_sequence(tenant, unit, items, start)
                return Response(
                    {
                        "items": serialize_plan(plan),
                        "total": str(sum(row["service"].price for row in plan)),
                    }
                )
            key = str(
                request.headers.get("Idempotency-Key")
                or data.get("idempotency_key")
                or ""
            )
            if not key or len(key) > 100:
                raise ValidationError("Identificador da reserva inválido.")
            fingerprint = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            with transaction.atomic():
                Unit.objects.select_for_update().get(
                    pk=unit.pk, tenant=tenant, active=True
                )
                # The shared unit lock serializes group and individual bookings.
                list(
                    Professional.objects.select_for_update()
                    .filter(tenant=tenant, unit=unit, active=True)
                    .order_by("pk")
                )
                existing = AppointmentBundle.objects.filter(
                    tenant=tenant, idempotency_key=key
                ).first()
                if existing:
                    if existing.fingerprint != fingerprint:
                        raise ValidationError(
                            "Identificador já utilizado em outra reserva."
                        )
                    return Response(
                        {
                            "items": [
                                _booking_response(request, row, replay=True).data
                                for row in existing.appointments.select_related(
                                    "tenant",
                                    "service",
                                    "professional",
                                    "unit",
                                    "customer",
                                ).order_by("starts_at")
                            ],
                            "idempotent_replay": True,
                        }
                    )
                plan = plan_sequence(tenant, unit, items, start)
                bundle = AppointmentBundle.objects.create(
                    tenant=tenant,
                    unit=unit,
                    idempotency_key=key,
                    fingerprint=fingerprint,
                )
                created = []
                for index, row in enumerate(plan):
                    payload = {
                        **dict(data),
                        "service_id": row["service"].pk,
                        "professional_id": row["professional"].pk,
                        "starts_at": row["starts_at"].isoformat(),
                        "product_ids": [],
                    }
                    child_key = hashlib.sha256(
                        f"bundle:{tenant.pk}:{key}:{index}".encode()
                    ).hexdigest()
                    result = PublicBookingAPIView().post(
                        DelegatedRequest(request, payload, child_key), slug
                    )
                    if result.status_code >= 400:
                        raise ValidationError(
                            result.data.get(
                                "detail", "Não foi possível reservar a sequência."
                            )
                        )
                    appointment = Appointment.objects.get(
                        pk=result.data["id"], tenant=tenant
                    )
                    bundle.appointments.add(appointment)
                    created.append(result.data)
                return Response(
                    {
                        "items": created,
                        "total": str(sum(row["service"].price for row in plan)),
                        "idempotent_replay": False,
                    },
                    status=201,
                )
        except (ValidationError, ValueError, TypeError) as exc:
            detail = (
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Dados inválidos para a reserva."
            )
            return Response({"detail": detail}, status=409)


def bundle_page(request, slug):
    from django.http import Http404

    tenant = _tenant(slug)
    if not tenant or tenant.deleted_at or tenant.archived_at:
        raise Http404
    from billing.segment_access import segment_enabled

    if segment_enabled(tenant, "arena") or segment_enabled(tenant, "auto"):
        raise Http404
    units = tenant.units.filter(active=True).order_by("-is_primary", "name")
    unit = _selected_unit(tenant, request.GET.get("unit"))
    services = Service.objects.filter(tenant=tenant, active=True)
    from django.db.models import Q

    if unit:
        services = services.filter(Q(unit=unit) | Q(unit__isnull=True))
    professionals = Professional.objects.filter(tenant=tenant, unit=unit, active=True)
    settings = AvailabilityService().settings(tenant, unit)
    return render(
        request,
        "scheduling/bundle_booking.html",
        {
            "tenant": tenant,
            "units": units,
            "selected_unit": unit,
            "services": services,
            "professionals": professionals,
            "public_today": timezone.now()
            .astimezone(ZoneInfo(tenant.timezone or "America/Recife"))
            .date()
            .isoformat(),
            "attempt_key": secrets.token_urlsafe(32),
            "payment_settings": settings,
        },
    )
