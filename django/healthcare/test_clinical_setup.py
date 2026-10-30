from django.test import TestCase, Client
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import User
from billing.models import Module, TenantModule
from tenants.models import Tenant
from scheduling.models import Professional, Customer
from core.models import AuditLog
from .models import ClinicalRegistration
from .services import create_record, clinical_records_for
from .clinical_activation import ClinicalActivationForm, activate_clinician


class ClinicalDashboardSetupTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Clínica Fisio",slug="fisio-clinical-setup",category="fisioterapia")
        self.owner=User.objects.create_user(
            email="owner-fisio-setup@example.test",password="GoodPassword123!",
            tenant=self.tenant,role="owner",
        )
        self.client.force_login(self.owner)

    def test_unlicensed_owner_sees_setup_not_records(self):
        module=Module.objects.create(slug="medical_records",name="Prontuários",active=True)
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        response=self.client.get(reverse("clinical-dashboard"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"vinculada a um profissional clínico autorizado")
        self.assertNotIn("patients",response.context)

    def test_unentitled_owner_sees_module_activation_not_403(self):
        response=self.client.get(reverse("clinical-dashboard"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"medical_records")

    def test_reception_cannot_use_activation_to_bypass_permissions(self):
        reception=User.objects.create_user(email="recepcao-fisio@example.test",
            password="GoodPassword123!",tenant=self.tenant,role="reception")
        self.client.force_login(reception)
        response=self.client.get(reverse("clinical-dashboard"))
        self.assertEqual(response.status_code,403)

    def activation_fixture(self, category="fisioterapia"):
        self.tenant.category = category
        self.tenant.save()
        module, _ = Module.objects.get_or_create(slug="medical_records", defaults={"name": "Prontuários", "active": True})
        TenantModule.objects.update_or_create(tenant=self.tenant, module=module, defaults={"enabled": True})
        self.profile = Professional.objects.create(tenant=self.tenant, name=self.tenant.name)
        return dict(professional=self.profile.pk, professional_name="Ana Clínica Teste", council="CRO" if category=="odontologia" else "CREFITO", number="12345", jurisdiction="PE" if category=="odontologia" else "1", specialties="", attestation="on")

    def test_existing_owner_can_explicitly_link_included_profile_without_new_seat(self):
        data = self.activation_fixture()
        response = self.client.get(reverse("clinical-dashboard"))
        self.assertContains(response, "Configurar meu vínculo clínico")
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.user_id)
        self.assertNotIn("patients", response.context)
        response = self.client.post(reverse("clinical-dashboard"), data)
        self.assertRedirects(response, reverse("physio-assessments"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_id, self.owner.pk)
        self.assertEqual(self.profile.name, self.tenant.name)
        self.assertEqual(Professional.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(self.profile.clinical_registration.professional_name, data["professional_name"])
        self.assertEqual(AuditLog.objects.filter(action="clinical.profile.self_activated", user=self.owner).count(), 1)
        self.client.post(reverse("clinical-dashboard"), data)
        self.assertEqual(Professional.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action="clinical.profile.self_activated", user=self.owner).count(), 1)

    def test_dental_owner_keeps_company_profile_and_uses_cro(self):
        data = self.activation_fixture("odontologia")
        module, _ = Module.objects.get_or_create(slug="dentistry", defaults={"name": "Odontologia", "active": True})
        TenantModule.objects.update_or_create(tenant=self.tenant, module=module, defaults={"enabled": True})
        response = self.client.post(reverse("clinical-dashboard"), data)
        self.assertRedirects(response, reverse("dental-assessments"))
        self.assertEqual(Professional.objects.filter(tenant=self.tenant, active=True).count(), 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.clinical_registration.jurisdiction, "PE")

    def test_identity_attestation_and_correct_council_are_required(self):
        data = self.activation_fixture()
        for changes in ({"attestation": ""}, {"professional_name": ""}, {"professional_name": self.tenant.name}, {"jurisdiction": "PE"}, {"council": "CRO", "jurisdiction": "PE"}, {"number": "<invalid>"}):
            with self.subTest(changes=changes):
                response = self.client.post(reverse("clinical-dashboard"), {**data, **changes})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["activation_form"].errors)
                self.profile.refresh_from_db()
                self.assertIsNone(self.profile.user_id)
                self.assertFalse(ClinicalRegistration.objects.filter(professional=self.profile).exists())

    def test_foreign_inactive_and_other_users_profiles_cannot_be_taken_over(self):
        data = self.activation_fixture()
        other = Tenant.objects.create(name="Outra clínica", slug="other-setup-clinic")
        colleague = User.objects.create_user(email="colleague-setup@example.test", tenant=self.tenant, role="professional")
        foreign = Professional.objects.create(tenant=other, name="Outro")
        inactive = Professional.objects.create(tenant=self.tenant, name="Inativo", active=False)
        occupied = Professional.objects.create(tenant=self.tenant, name="Colega", user=colleague)
        for profile in (foreign, inactive, occupied):
            response = self.client.post(reverse("clinical-dashboard"), {**data, "professional": profile.pk})
            self.assertEqual(response.status_code, 200)
            self.assertIn("professional", response.context["activation_form"].errors)
        occupied.refresh_from_db()
        self.assertEqual(occupied.user_id, colleague.pk)

    def test_roles_and_missing_entitlement_cannot_self_activate(self):
        data = self.activation_fixture()
        for role in ("reception", "manager", "professional", "master"):
            actor = User.objects.create_user(email=role+"-activation@example.test", tenant=self.tenant, role=role)
            self.client.force_login(actor)
            self.assertEqual(self.client.post(reverse("clinical-dashboard"), data).status_code, 403)
        self.client.force_login(self.owner)
        TenantModule.objects.filter(tenant=self.tenant, module__slug="medical_records").update(enabled=False)
        response = self.client.post(reverse("clinical-dashboard"), data)
        self.assertContains(response, "medical_records")
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.user_id)

    def test_linking_profile_does_not_grant_previous_clinicians_records(self):
        data = self.activation_fixture()
        clinician = User.objects.create_user(email="previous-clinician@example.test", tenant=self.tenant, role="professional")
        self.profile.user = clinician
        self.profile.save()
        patient = Customer.objects.create(tenant=self.tenant, name="Paciente fictício")
        entry = create_record(tenant=self.tenant, customer=patient, professional=self.profile, user=clinician, title="Registro anterior", content="Conteúdo confidencial de outro profissional")
        self.profile.user = None
        self.profile.save()
        response = self.client.post(reverse("clinical-dashboard"), data)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(clinical_records_for(user=self.owner, tenant=self.tenant).filter(pk=entry.pk).exists())

    def test_changed_profile_is_rechecked_inside_activation_transaction(self):
        data = self.activation_fixture()
        form = ClinicalActivationForm(data, user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)
        colleague = User.objects.create_user(email="racing-setup@example.test", tenant=self.tenant, role="professional")
        Professional.objects.filter(pk=self.profile.pk).update(user=colleague)
        with self.assertRaises(ValidationError):
            activate_clinician(user=self.owner, form=form)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_id, colleague.pk)
        self.assertFalse(ClinicalRegistration.objects.filter(professional=self.profile).exists())

    def test_activation_post_requires_csrf(self):
        data = self.activation_fixture()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(reverse("clinical-dashboard"), data).status_code, 403)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.user_id)
