from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from accounts.models import User
from tenants.models import Tenant, Unit
from scheduling.models import (
    Appointment,
    Customer,
    Service,
    Professional,
    ProfessionalAvailability,
    AppointmentWorkNote,
)
from scheduling.availability import AvailabilityService
from engagement.models import WaitlistEntry
from communications.models import (
    ChatbotFlow,
    WhatsAppConversation,
    TenantWhatsAppConnection,
)
from core.crypto import decrypt_text
from .models import BeautySettings, SalonResource, RecoveryOffer
from .stages import configure_stages
from .recovery import offer_vacancy, accept_offer, expire_offers


class IntelligenceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Salão",
            slug="beauty-test",
            public_slug="beauty-test",
            category="Barbearia",
            status="active",
            public_enabled=True,
            public_booking_enabled=True,
        )
        self.unit = Unit.objects.create(tenant=self.tenant, name="Centro", active=True)
        self.pro = Professional.objects.create(
            tenant=self.tenant, unit=self.unit, name="João"
        )
        self.other_pro = Professional.objects.create(
            tenant=self.tenant, unit=self.unit, name="Ana"
        )
        self.service = Service.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Coloração",
            duration_minutes=90,
            price=150,
        )
        self.cut = Service.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            name="Corte",
            duration_minutes=20,
            price=30,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Maria",
            phone="5581999991234",
            consent_marketing=True,
        )
        self.day = timezone.localdate() + timedelta(days=2)
        self.start = datetime.combine(
            self.day, time(10), tzinfo=ZoneInfo("America/Recife")
        )
        for pro in [self.pro, self.other_pro]:
            ProfessionalAvailability.objects.create(
                tenant=self.tenant,
                professional=pro,
                weekday=self.day.isoweekday(),
                start_time=time(8),
                end_time=time(19),
            )
        self.owner = User.objects.create_user(
            email="beauty@test.com",
            password="LongPassword123!",
            tenant=self.tenant,
            role="owner",
        )
        TenantWhatsAppConnection.objects.create(tenant=self.tenant, enabled=True)
        self.config = BeautySettings.objects.create(
            tenant=self.tenant, booking_assistant=True, recovery_enabled=True
        )

    def appointment(
        self, service=None, pro=None, start=None, status="confirmed", customer=None
    ):
        service = service or self.service
        start = start or self.start
        return Appointment.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            customer=customer or self.customer,
            service=service,
            professional=pro or self.pro,
            starts_at=start,
            ends_at=start + timedelta(minutes=service.duration_minutes),
            status=status,
            service_price_snapshot=service.price,
        )

    def stages(self):
        resource = SalonResource.objects.create(
            tenant=self.tenant, unit=self.unit, name="Cadeira 1", kind="chair"
        )
        configure_stages(
            self.tenant,
            self.service,
            [
                {
                    "name": "Aplicação",
                    "minutes": 20,
                    "professional_required": True,
                    "resource": resource,
                },
                {
                    "name": "Pausa",
                    "minutes": 40,
                    "professional_required": False,
                    "resource": resource,
                },
                {
                    "name": "Finalização",
                    "minutes": 30,
                    "professional_required": True,
                    "resource": resource,
                },
            ],
        )
        return resource

    def test_pause_releases_professional_but_keeps_resource(self):
        resource = self.stages()
        self.appointment()
        begin = self.start + timedelta(minutes=25)
        end = begin + timedelta(minutes=20)
        engine = AvailabilityService()
        self.assertTrue(
            engine.is_available(self.tenant, self.pro, begin, end, service=self.cut)
        )
        self.assertFalse(
            engine.is_available(
                self.tenant,
                self.pro,
                self.start,
                self.start + timedelta(minutes=20),
                service=self.cut,
            )
        )
        self.assertFalse(
            engine.is_available(
                self.tenant,
                self.other_pro,
                self.start,
                self.start + timedelta(minutes=90),
                service=self.service,
            )
        )
        self.assertEqual(resource.stagereservation_set.count(), 3)

    def test_resource_conflict_cannot_be_bypassed_by_direct_save(self):
        self.stages()
        self.appointment()
        with self.assertRaises(ValidationError):
            self.appointment(pro=self.other_pro)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_invalid_stage_sum_and_cross_tenant_resource(self):
        with self.assertRaises(ValidationError):
            configure_stages(
                self.tenant,
                self.service,
                [
                    {
                        "name": "X",
                        "minutes": 5,
                        "professional_required": True,
                        "resource": None,
                    }
                ],
            )
        other = Tenant.objects.create(name="Outra", slug="other-beauty")
        unit = Unit.objects.create(tenant=other, name="Outra")
        resource = SalonResource.objects.create(
            tenant=other, unit=unit, name="Outra", kind="wash"
        )
        with self.assertRaises(ValidationError):
            configure_stages(
                self.tenant,
                self.service,
                [
                    {
                        "name": "X",
                        "minutes": 90,
                        "professional_required": True,
                        "resource": resource,
                    }
                ],
            )

    def waitlist(self, **extra):
        return WaitlistEntry.objects.create(
            tenant=self.tenant,
            unit=self.unit,
            customer=self.customer,
            service=self.service,
            preferred_date=self.day,
            **extra,
        )

    def test_recovery_holds_slot_and_accepts_once(self):
        original = self.appointment(status="cancelled")
        self.waitlist()
        offer = offer_vacancy(original.pk)
        self.assertIsNotNone(offer)
        self.assertEqual(offer_vacancy(original.pk).pk, offer.pk)
        self.assertFalse(
            AvailabilityService().is_available(
                self.tenant, self.pro, self.start, self.start + timedelta(minutes=90)
            )
        )
        token = decrypt_text(offer.token_encrypted)
        self.assertEqual(accept_offer(token).status, "accepted")
        self.assertEqual(accept_offer(token).status, "accepted")
        self.assertEqual(WaitlistEntry.objects.get().status, "booked")
        self.assertEqual(Appointment.objects.filter(status="confirmed").count(), 1)

    def test_expiry_frees_slot_and_rejects_late_accept(self):
        original = self.appointment(status="cancelled")
        self.waitlist()
        offer = offer_vacancy(original.pk)
        RecoveryOffer.objects.filter(pk=offer.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        expire_offers(self.tenant)
        with self.assertRaises(ValidationError):
            accept_offer(decrypt_text(offer.token_encrypted))
        self.assertTrue(
            AvailabilityService().is_available(
                self.tenant, self.pro, self.start, self.start + timedelta(minutes=90)
            )
        )

    def test_no_marketing_consent_no_offer(self):
        original = self.appointment(status="cancelled")
        self.waitlist()
        self.customer.consent_marketing = False
        self.customer.save()
        self.assertIsNone(offer_vacancy(original.pk))

    def test_waitlist_preferences_respected(self):
        original = self.appointment(status="cancelled")
        self.waitlist(professional=self.other_pro)
        self.assertIsNone(offer_vacancy(original.pk))

    def test_public_offer_page_get_does_not_confirm(self):
        original = self.appointment(status="cancelled")
        self.waitlist()
        offer = offer_vacancy(original.pk)
        response = self.client.get(
            reverse(
                "beauty-recovery-accept", args=[decrypt_text(offer.token_encrypted)]
            )
        )
        self.assertEqual(response.status_code, 200, response.content)
        offer.refresh_from_db()
        self.assertEqual(offer.status, "held")

    def test_reception_cannot_read_management_dashboard(self):
        self.owner.role = "reception"
        self.owner.save()
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("beauty-intelligence")).status_code, 403
        )

    def test_management_dashboard_renders_and_has_no_fake_income(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("beauty-intelligence"))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.context["received"], Decimal("0"))

    def test_memory_is_encrypted_and_repeat_preserves_reference(self):
        a = self.appointment()
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("appointment-work-notes", args=[a.pk]),
            {
                "text": "Corte habitual",
                "cut_style": "Máquina 2",
                "color_formula": "6.0 + 7.1",
            },
        )
        self.assertEqual(response.status_code, 302, response.content)
        note = AppointmentWorkNote.objects.get()
        self.assertNotIn("Máquina", note.technical_encrypted)
        self.assertEqual(note.technical["cut_style"], "Máquina 2")
        response = self.client.get(
            reverse("appointment-work-notes", args=[a.pk]), {"repeat": note.pk}
        )
        self.assertEqual(response.context["form"].initial["color_formula"], "6.0 + 7.1")

    def test_ai_booking_requires_explicit_confirmation_and_uses_real_availability(self):
        from communications.beauty_booking import answer

        flow = ChatbotFlow.objects.create(tenant=self.tenant, enabled=True)
        conv = WhatsAppConversation.objects.create(
            tenant=self.tenant,
            wa_id="5581999991234",
            customer=self.customer,
            contact_name="Maria",
            last_message_at=timezone.now(),
        )
        context = {"variables": {"contact_phone": self.customer.phone}}
        parsed = {
            "intent": "book",
            "service_id": self.cut.pk,
            "date": self.day.isoformat(),
            "time": "10:00",
        }
        with patch("communications.beauty_booking.extract", return_value=parsed):
            response = answer(conv, flow, context, "Quero corte depois das 10", "one")
        self.assertIn("opções", response["messages"][0])
        response = answer(conv, flow, context, "1", "two")
        self.assertIn("Confirma", response["messages"][0])
        self.assertFalse(Appointment.objects.exists())
        response = answer(conv, flow, context, "sim", "three")
        self.assertIn("Agendamento confirmado", response["messages"][0])
        self.assertEqual(Appointment.objects.get().source, "whatsapp")

    def test_ai_failure_hands_off_without_booking(self):
        from communications.beauty_booking import answer

        flow = ChatbotFlow.objects.create(tenant=self.tenant, enabled=True)
        conv = WhatsAppConversation.objects.create(
            tenant=self.tenant, wa_id="5581999991234", last_message_at=timezone.now()
        )
        with patch("communications.beauty_booking.extract", side_effect=ValueError):
            response = answer(conv, flow, {"variables": {}}, "quero agendar", "one")
        self.assertTrue(response["handoff"])
        self.assertFalse(Appointment.objects.exists())

    def test_multiple_services_are_booked_as_one_atomic_sequence(self):
        from communications.beauty_booking import answer

        flow = ChatbotFlow.objects.create(tenant=self.tenant, enabled=True)
        conv = WhatsAppConversation.objects.create(
            tenant=self.tenant,
            wa_id=self.customer.phone,
            customer=self.customer,
            last_message_at=timezone.now(),
        )
        context = {"variables": {"contact_phone": self.customer.phone}}
        parsed = {
            "intent": "book",
            "service_ids": [self.cut.pk, self.service.pk],
            "date": self.day.isoformat(),
            "time": "10:00",
        }
        with patch("communications.beauty_booking.extract", return_value=parsed):
            answer(conv, flow, context, "Quero corte e coloração", "one")
        answer(conv, flow, context, "1", "two")
        response = answer(conv, flow, context, "sim", "three")
        self.assertIn("Agendamento confirmado", response["messages"][0])
        self.assertEqual(Appointment.objects.count(), 2)
        rows = list(Appointment.objects.order_by("starts_at"))
        self.assertGreaterEqual(rows[1].starts_at, rows[0].ends_at)

    def test_recovery_report_counts_only_actual_nonvoided_receipts(self):
        from .models import BarberCommand, BarberCommandPayment

        original = self.appointment(status="cancelled")
        self.waitlist()
        offer = offer_vacancy(original.pk)
        accept_offer(decrypt_text(offer.token_encrypted))
        command = BarberCommand.objects.create(
            tenant=self.tenant,
            appointment=offer.appointment,
            customer=self.customer,
            status="closed",
            opened_by=self.owner,
            opened_at=timezone.now(),
            total_amount=150,
        )
        BarberCommandPayment.objects.create(
            tenant=self.tenant,
            command=command,
            amount=50,
            method="cash",
            user=self.owner,
            received_at=timezone.now(),
        )
        BarberCommandPayment.objects.create(
            tenant=self.tenant,
            command=command,
            amount=100,
            method="pix",
            user=self.owner,
            received_at=timezone.now(),
            voided_at=timezone.now(),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("beauty-intelligence"))
        self.assertEqual(response.context["received"], Decimal("50"))

    def test_optout_works_even_while_human_is_assigned(self):
        from communications.tenant_whatsapp import mark_inbound_appointment

        conv = WhatsAppConversation.objects.create(
            tenant=self.tenant,
            wa_id=self.customer.phone,
            customer=self.customer,
            status="human",
            last_message_at=timezone.now(),
        )
        mark_inbound_appointment(conv, "SAIR")
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.consent_marketing)
