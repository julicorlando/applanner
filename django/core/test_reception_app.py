from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant


class ReceptionAppTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Clínica Recepção Exemplo", slug="clinica-recepcao-exemplo", category="estetica")
        self.reception = User.objects.create_user(email="recepcao-app@exemplo.test", tenant=self.tenant, role="reception")
        self.doctor = User.objects.create_user(email="dentista-app@exemplo.test", tenant=self.tenant, role="professional")
        self.colleague = User.objects.create_user(email="colega-app@exemplo.test", tenant=self.tenant, role="professional")
        self.prof = Professional.objects.create(tenant=self.tenant, user=self.doctor, name="Dra. Agenda Exemplo")
        self.other_prof = Professional.objects.create(tenant=self.tenant, user=self.colleague, name="Dr. Outro Exemplo")
        service = Service.objects.create(tenant=self.tenant, name="Avaliação", duration_minutes=30, price=0)
        start = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        self.mine = Appointment.objects.create(tenant=self.tenant, customer=Customer.objects.create(tenant=self.tenant, name="Paciente Da Dra"),
                                               professional=self.prof, service=service, starts_at=start,
                                               ends_at=start + timedelta(minutes=30), status="confirmed")
        self.theirs = Appointment.objects.create(tenant=self.tenant, customer=Customer.objects.create(tenant=self.tenant, name="Paciente Do Colega"),
                                                 professional=self.other_prof, service=service, starts_at=start + timedelta(hours=1),
                                                 ends_at=start + timedelta(hours=1, minutes=30), status="confirmed")

    def test_reception_sees_the_day_and_registers_arrival(self):
        self.client.force_login(self.reception)
        response = self.client.get(reverse("reception-panel"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paciente Da Dra")
        self.assertContains(response, "Paciente Do Colega")
        self.assertContains(response, reverse("reception-app-manifest"))
        result = self.client.post(reverse("reception-panel"), {"action": "arrived", "appointment": self.mine.pk})
        self.assertRedirects(result, reverse("reception-panel"), fetch_redirect_response=False)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, "waiting")

    def test_professional_uses_the_app_with_own_scope_only(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("reception-panel"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paciente Da Dra")
        self.assertNotContains(response, "Paciente Do Colega")
        self.assertNotContains(response, "Paciente chegou")
        self.assertEqual(self.client.post(reverse("reception-panel"), {"action": "arrived", "appointment": self.mine.pk}).status_code, 403)

    def test_manifest_icon_and_windows_installer(self):
        manifest = self.client.get(reverse("reception-app-manifest")).json()
        self.assertEqual(manifest["start_url"], reverse("reception-panel"))
        self.assertEqual(manifest["name"], "ApPlanner Recepção")
        self.assertTrue(self.client.get(reverse("reception-app-ico")).content.startswith(b"\x00\x00\x01\x00"))
        self.client.force_login(self.reception)
        self.assertEqual(self.client.get(reverse("reception-app-install")).status_code, 200)
        installer = self.client.get(reverse("reception-app-windows"))
        self.assertIn("attachment", installer["Content-Disposition"])
        self.assertIn(b"-EncodedCommand", installer.content)

    def test_offline_mode_card_only_for_clinic_staff_and_worker_falls_back(self):
        self.client.force_login(self.reception)
        self.assertNotContains(self.client.get(reverse("reception-panel")), 'id="rp-offline"')
        clinic = Tenant.objects.create(name="Clínica Offline Exemplo", slug="clinica-offline-exemplo", category="fisioterapia")
        desk = User.objects.create_user(email="recepcao-offline@exemplo.test", tenant=clinic, role="reception")
        self.client.force_login(desk)
        response = self.client.get(reverse("reception-panel"))
        self.assertContains(response, 'id="rp-offline"')
        self.assertContains(response, reverse("clinical-offline-shell"))
        self.assertContains(response, "reception-offline")
        worker = self.client.get(reverse("web-app-worker")).content.decode()
        self.assertIn('const RECEPTION_PANEL = "%s"' % reverse("reception-panel"), worker)
        self.assertIn("url.pathname === RECEPTION_PANEL", worker)
        shell = self.client.get(reverse("clinical-offline-shell"))
        self.assertContains(shell, reverse("reception-panel"))
        self.assertNotContains(shell, "recepcao-offline@exemplo.test")
