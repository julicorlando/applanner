from datetime import time, timedelta
from unittest.mock import patch
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from tenants.models import Tenant, Unit
from scheduling.models import (
    Appointment,
    AppointmentWorkNote,
    Customer,
    Professional,
    ProfessionalAvailability,
    ProfessionalTimeOff,
    Service,
)
from scheduling.discovery import today_slot
from scheduling.availability import AvailabilityService
from finance.models import Product


class ReleaseCompletionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant = Tenant.objects.create(
            name="Empresa",
            slug="release-completion",
            public_slug="release-completion",
            category="salao",
            status="active",
            public_enabled=True,
            public_booking_enabled=True,
        )
        self.unit = Unit.objects.create(
            tenant=self.tenant, name="Centro", is_primary=True
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant, name="Cliente", phone="81900000001"
        )
        self.pro_user = User.objects.create_user(
            email="release-pro@example.test", role="professional", tenant=self.tenant
        )
        self.professional = Professional.objects.create(
            tenant=self.tenant, unit=self.unit, name="Ana", user=self.pro_user
        )
        self.second_professional = Professional.objects.create(
            tenant=self.tenant, unit=self.unit, name="Bruno"
        )
        self.service = Service.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Corte",
            duration_minutes=30,
            price=50,
        )
        self.second = Service.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Barba",
            duration_minutes=30,
            price=30,
        )
        self.tomorrow = timezone.localtime() + timedelta(days=1)
        self.start = self.tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
        for pro in [self.professional, self.second_professional]:
            for weekday in range(1, 8):
                ProfessionalAvailability.objects.create(
                    tenant=self.tenant,
                    professional=pro,
                    weekday=weekday,
                    start_time=time(8),
                    end_time=time(20),
                )

    def appt(self, **values):
        data = dict(
            tenant=self.tenant,
            unit=self.unit,
            customer=self.customer,
            professional=self.professional,
            service=self.service,
            starts_at=self.start,
            ends_at=self.start + timedelta(minutes=30),
            status="confirmed",
        )
        data.update(values)
        return Appointment.objects.create(**data)

    def bundle(self):
        return {
            "unit_id": self.unit.pk,
            "items": [
                {
                    "service_id": self.service.pk,
                    "professional_id": self.professional.pk,
                },
                {
                    "service_id": self.second.pk,
                    "professional_id": self.second_professional.pk,
                },
            ],
            "starts_at": self.start.isoformat(),
            "name": "Cliente",
            "phone": "81900000001",
            "payment_choice": "on_site",
        }

    def test_multiple_services_are_reserved_together_and_replay_does_not_duplicate(
        self,
    ):
        data = self.bundle()
        url = reverse("public-bundle-api", args=[self.tenant.slug])
        first = self.client.post(
            url,
            data,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="bundle-release",
        )
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(len(first.json()["items"]), 2)
        second = self.client.post(
            url,
            data,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="bundle-release",
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Appointment.objects.count(), 2)
        self.assertEqual(
            first.json()["items"][0]["id"], second.json()["items"][0]["id"]
        )

    def test_unavailable_second_service_creates_no_partial_reservation(self):
        self.appt(
            professional=self.second_professional,
            service=self.second,
            starts_at=self.start + timedelta(minutes=30),
            ends_at=self.start + timedelta(hours=1),
        )
        response = self.client.post(
            reverse("public-bundle-api", args=[self.tenant.slug]),
            self.bundle(),
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="bundle-conflict",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_failure_in_second_booking_rolls_back_first_and_queued_notifications(self):
        from scheduling.public_api import PublicBookingAPIView
        from rest_framework.response import Response
        from communications.models import Notification

        original = PublicBookingAPIView.post
        calls = []

        def fail_second(view, request, slug):
            calls.append(1)
            return (
                original(view, request, slug)
                if len(calls) == 1
                else Response({"detail": "Simulação de conflito tardio"}, status=409)
            )

        with patch.object(PublicBookingAPIView, "post", fail_second):
            response = self.client.post(
                reverse("public-bundle-api", args=[self.tenant.slug]),
                self.bundle(),
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="late-conflict",
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_bundle_rejects_service_from_another_company(self):
        other = Tenant.objects.create(name="Outra", slug="bundle-other")
        service = Service.objects.create(
            tenant=other, name="Segredo", duration_minutes=30, price=1
        )
        data = self.bundle()
        data["items"][1]["service_id"] = service.pk
        response = self.client.post(
            reverse("public-bundle-api", args=[self.tenant.slug]),
            data,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="foreign-service",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_professional_can_block_only_free_periods(self):
        self.client.force_login(self.pro_user)
        response = self.client.post(
            reverse("professional-blocks"),
            {
                "starts_at": self.start.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "reason": "Pausa",
            },
        )
        self.assertEqual(response.status_code, 302, response.content)
        row = ProfessionalTimeOff.objects.get()
        self.assertEqual(row.professional_id, self.professional.pk)
        self.assertFalse(
            AvailabilityService().is_available(
                self.tenant,
                self.professional,
                self.start,
                self.start + timedelta(minutes=30),
            )
        )

    def test_block_rejects_existing_appointment(self):
        self.appt()
        self.client.force_login(self.pro_user)
        response = self.client.post(
            reverse("professional-blocks"),
            {
                "starts_at": self.start.strftime("%Y-%m-%dT%H:%M"),
                "ends_at": (self.start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
                "reason": "Pausa",
            },
        )
        self.assertContains(response, "Há um agendamento")
        self.assertEqual(ProfessionalTimeOff.objects.count(), 0)

    def test_professional_cannot_cancel_other_professional_block(self):
        row = ProfessionalTimeOff.objects.create(
            tenant=self.tenant,
            professional=self.second_professional,
            created_by=self.pro_user,
            starts_at=self.start,
            ends_at=self.start + timedelta(hours=1),
        )
        self.client.force_login(self.pro_user)
        self.assertEqual(
            self.client.post(
                reverse("professional-blocks"), {"action": "cancel", "block": row.pk}
            ).status_code,
            404,
        )
        row.refresh_from_db()
        self.assertEqual(row.status, "active")

    def test_private_note_does_not_allow_another_professional_or_public_media_alias(
        self,
    ):
        appt = self.appt()
        row = AppointmentWorkNote.objects.create(
            tenant=self.tenant,
            appointment=appt,
            user=self.pro_user,
            text="Preferência privada",
        )
        outsider = User.objects.create_user(
            email="other-release-pro@example.test",
            tenant=self.tenant,
            role="professional",
        )
        Professional.objects.create(
            tenant=self.tenant, unit=self.unit, name="Outra", user=outsider
        )
        self.client.force_login(outsider)
        self.assertEqual(
            self.client.get(
                reverse("appointment-work-notes", args=[appt.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("appointment-work-photo", args=[row.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/media/private/worknotes/test.jpg").status_code, 404
        )

    def test_today_discovery_matches_canonical_availability(self):
        now = timezone.localtime().replace(hour=8, minute=0, second=0, microsecond=0)
        with patch("django.utils.timezone.now", return_value=now):
            row = today_slot(self.tenant, self.unit)
            self.assertIsNotNone(row)
            start = now.replace(
                hour=int(row["label"].split(":")[0]),
                minute=int(row["label"].split(":")[1]),
            )
            self.assertTrue(
                AvailabilityService().is_available(
                    self.tenant, self.professional, start, start + timedelta(minutes=30)
                )
            )
            for pro in [self.professional, self.second_professional]:
                ProfessionalTimeOff.objects.create(
                    tenant=self.tenant,
                    professional=pro,
                    created_by=self.pro_user,
                    starts_at=now,
                    ends_at=now + timedelta(hours=12),
                )
            self.assertIsNone(today_slot(self.tenant, self.unit))

    def test_consumables_not_public_or_bookable_as_products(self):
        product = Product.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Insumo privado",
            kind="internal",
            stock=5,
            sale_price=0,
        )
        self.assertNotContains(
            self.client.get(reverse("tenant-public", args=[self.tenant.slug])),
            product.name,
        )
        data = {
            "unit_id": self.unit.pk,
            "service_id": self.service.pk,
            "professional_id": self.professional.pk,
            "starts_at": self.start.isoformat(),
            "name": "Cliente",
            "phone": "81900000001",
            "product_ids": [product.pk],
        }
        response = self.client.post(
            f"/api/public/{self.tenant.slug}/book/",
            data,
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_calendar_move_validates_conflicts_and_cross_tenant(self):
        owner = User.objects.create_user(
            email="calendar-owner@example.test", role="owner", tenant=self.tenant
        )
        self.client.force_login(owner)
        row = self.appt()
        url = reverse("operation-calendar-move", args=[row.pk])
        self.appt(
            starts_at=self.start + timedelta(hours=1),
            ends_at=self.start + timedelta(hours=1, minutes=30),
        )
        response = self.client.post(
            url,
            {"starts_at": (self.start + timedelta(hours=1)).isoformat()},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409, response.content)
        row.refresh_from_db()
        self.assertEqual(row.starts_at, self.start)
        response = self.client.post(
            url,
            {"starts_at": (self.start + timedelta(hours=2)).isoformat()},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        row.refresh_from_db()
        self.assertEqual(row.starts_at, self.start + timedelta(hours=2))
        self.assertEqual(
            self.client.post(url, "[1]", content_type="application/json").status_code,
            409,
        )
        outsider = User.objects.create_user(
            email="calendar-outsider@example.test",
            role="owner",
            tenant=Tenant.objects.create(name="Fora", slug="calendar-outside"),
        )
        self.client.force_login(outsider)
        self.assertIn(
            self.client.post(
                url,
                {"starts_at": self.start.isoformat()},
                content_type="application/json",
            ).status_code,
            [403, 404],
        )

    def test_global_search_professional_only_sees_own_customer_appointments(self):
        self.appt()
        secret = Customer.objects.create(
            tenant=self.tenant, name="Segredo profissional"
        )
        self.appt(customer=secret, professional=self.second_professional)
        self.client.force_login(self.pro_user)
        response = self.client.get(reverse("professional-search"), {"q": "Segredo"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, secret.name)
        response = self.client.get(
            reverse("professional-search"), {"q": self.customer.name}
        )
        self.assertContains(response, self.customer.name)

    def test_bench_consumption_requires_module_and_own_started_appointment(self):
        from billing.models import Module, TenantModule
        from finance.models import MaterialConsumption

        row = self.appt()
        product = Product.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            kind="internal",
            name="Insumo bancada",
            stock=5,
            sale_price=0,
        )
        self.client.force_login(self.pro_user)
        url = reverse("professional-materials", args=[row.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        module = Module.objects.create(slug="stock", name="Estoque")
        TenantModule.objects.create(tenant=self.tenant, module=module, enabled=True)
        payload = {
            "product": product.pk,
            "quantity": "1",
            "note": "Adicional",
            "key": "bench-consume",
        }
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.assertEqual(MaterialConsumption.objects.count(), 0)
        row.starts_at = timezone.now() - timedelta(minutes=20)
        row.ends_at = timezone.now() + timedelta(minutes=10)
        row.save()
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(MaterialConsumption.objects.count(), 1)
        product.refresh_from_db()
        self.assertEqual(product.stock, 4)
