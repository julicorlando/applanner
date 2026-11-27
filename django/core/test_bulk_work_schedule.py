from datetime import time

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from scheduling.models import Professional, ProfessionalAvailability, ProfessionalBreak
from tenants.models import Tenant, Unit

from .bulk_work_schedule import BulkWorkScheduleForm, create_work_schedules


class BulkWorkScheduleTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Empresa", slug="bulk-work-demo", category="Barbearia", status="active")
        self.unit = Unit.objects.create(tenant=self.tenant, name="Centro", is_primary=True)
        self.owner = User.objects.create_user(email="bulk-owner@example.test", role="owner", tenant=self.tenant)
        self.pros = [Professional.objects.create(tenant=self.tenant, unit=self.unit, name=name) for name in ["Ana", "Bia"]]
        self.data = {"professionals": [p.pk for p in self.pros], "weekdays": [1, 2, 3],
                     "start_time": "09:00", "end_time": "18:00", "break_start": "12:00", "break_end": "13:00"}
        self.url = reverse("bulk-work-schedule") + f"?unit={self.unit.pk}"

    def form(self, **overrides):
        return BulkWorkScheduleForm({**self.data, **overrides}, tenant=self.tenant, unit=self.unit)

    def test_multiple_professionals_days_breaks_and_identical_retry(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(create_work_schedules(tenant=self.tenant, unit=self.unit, data=form.cleaned_data), (6, 6))
        self.assertEqual(create_work_schedules(tenant=self.tenant, unit=self.unit, data=form.cleaned_data), (0, 0))
        self.assertEqual(ProfessionalAvailability.objects.count(), 6)
        self.assertEqual(ProfessionalBreak.objects.count(), 6)
        self.assertEqual(set(ProfessionalAvailability.objects.values_list("tenant_id", flat=True)), {self.tenant.pk})

    def test_optional_break_and_preservation_of_existing_pause(self):
        pause = ProfessionalBreak.objects.create(tenant=self.tenant, professional=self.pros[0], weekday=1,
                                                start_time=time(15), end_time=time(15, 15), label="Café")
        form = self.form(break_start="", break_end="")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(create_work_schedules(tenant=self.tenant, unit=self.unit, data=form.cleaned_data), (6, 0))
        pause.refresh_from_db()
        self.assertEqual(pause.label, "Café")
        self.assertTrue(pause.active)
        self.assertEqual(ProfessionalBreak.objects.count(), 1)

    def test_conflicting_last_day_leaves_whole_batch_untouched(self):
        original = ProfessionalAvailability.objects.create(tenant=self.tenant, professional=self.pros[-1],
                     weekday=3, start_time=time(8), end_time=time(17))
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            create_work_schedules(tenant=self.tenant, unit=self.unit, data=form.cleaned_data)
        self.assertEqual(ProfessionalAvailability.objects.count(), 1)
        self.assertEqual(ProfessionalBreak.objects.count(), 0)
        original.refresh_from_db()
        self.assertEqual(original.start_time, time(8))
        self.assertEqual(original.end_time, time(17))

    def test_invalid_journey_and_partial_or_outside_break(self):
        for values in [{"end_time": "08:00"}, {"break_end": ""}, {"break_start": "08:30"},
                       {"break_start": "13:30", "break_end": "13:00"}, {"break_end": "18:00"}]:
            with self.subTest(values=values):
                self.assertFalse(self.form(**values).is_valid())
        self.assertEqual(ProfessionalAvailability.objects.count(), 0)

    def test_other_tenant_unit_and_inactive_professional_are_rejected(self):
        other = Tenant.objects.create(name="Outra", slug="bulk-work-other")
        other_unit = Unit.objects.create(tenant=self.tenant, name="Outra unidade")
        for tenant, unit, active in [(other, None, True), (self.tenant, other_unit, True),
                                     (self.tenant, self.unit, False)]:
            pro = Professional.objects.create(tenant=tenant, unit=unit, name="Fora do escopo", active=active)
            self.assertFalse(self.form(professionals=[pro.pk]).is_valid())
        self.client.force_login(self.owner)
        foreign_unit = Unit.objects.create(tenant=other, name="Unidade de outra empresa")
        self.assertEqual(self.client.get(reverse("bulk-work-schedule"), {"unit": foreign_unit.pk}).status_code, 404)

    def test_overlapping_existing_break_rolls_back_and_preserves_original(self):
        pause = ProfessionalBreak.objects.create(tenant=self.tenant, professional=self.pros[-1], weekday=3,
                    start_time=time(12, 30), end_time=time(13, 30), label="Almoço existente")
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            create_work_schedules(tenant=self.tenant, unit=self.unit, data=form.cleaned_data)
        self.assertEqual(ProfessionalAvailability.objects.count(), 0)
        self.assertEqual(list(ProfessionalBreak.objects.values_list("pk", flat=True)), [pause.pk])

    def test_page_and_post_use_existing_portal_authorization(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.post(self.url, self.data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProfessionalAvailability.objects.count(), 6)
        for role in ["professional", "finance"]:
            user = User.objects.create_user(email=f"bulk-{role}@example.test", role=role, tenant=self.tenant)
            self.client.force_login(user)
            self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        self.assertEqual(ProfessionalAvailability.objects.count(), 6)

    def test_sidebar_and_schedule_list_have_bulk_action(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("portal-resource-list", args=["agenda", "expedientes"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("bulk-work-schedule"))

    def test_bulk_interval_is_used_by_real_booking_availability(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from scheduling.availability import AvailabilityService
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        create_work_schedules(tenant=self.tenant, unit=self.unit, data=form.cleaned_data)
        tz = ZoneInfo(self.tenant.timezone or "America/Recife")
        availability = AvailabilityService()
        self.assertTrue(availability.is_available(self.tenant, self.pros[0],
            datetime(2030, 2, 4, 10, tzinfo=tz), datetime(2030, 2, 4, 10, 30, tzinfo=tz), public_rules=False))
        self.assertFalse(availability.is_available(self.tenant, self.pros[0],
            datetime(2030, 2, 4, 12, tzinfo=tz), datetime(2030, 2, 4, 12, 30, tzinfo=tz), public_rules=False))
