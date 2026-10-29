from django.core.exceptions import ValidationError
from django.test import TestCase
from accounts.models import User
from billing.models import Module, TenantModule, TenantModuleAddon
from scheduling.models import Professional
from tenants.models import Tenant


class DentalCapacityTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Odonto",slug="dental-capacity",category="odontologia")
        self.first=Professional.objects.create(tenant=self.tenant,name="Dentista incluído")
        self.module,_=Module.objects.get_or_create(slug="dental-professional-extra",defaults={"name":"Dentista extra"})

    def test_direct_orm_creation_cannot_exceed_allowance(self):
        with self.assertRaises(ValidationError):
            Professional.objects.create(tenant=self.tenant,name="Sem vaga paga")

    def test_reception_user_does_not_consume_dentist_seat(self):
        User.objects.create_user(email="reception-capacity@example.test",tenant=self.tenant,role="reception")
        self.assertEqual(self.tenant.professionals.filter(active=True).count(),1)

    def test_pending_addon_does_not_unlock_seat(self):
        TenantModuleAddon.objects.create(tenant=self.tenant,module=self.module,quantity=2,monthly_price=10,status="pending")
        with self.assertRaises(ValidationError):
            Professional.objects.create(tenant=self.tenant,name="Aguardando pagamento")

    def test_active_addon_unlocks_only_its_contracted_quantity(self):
        TenantModuleAddon.objects.create(tenant=self.tenant,module=self.module,quantity=1,monthly_price=10,status="active")
        Professional.objects.create(tenant=self.tenant,name="Dentista adicional")
        with self.assertRaises(ValidationError):
            Professional.objects.create(tenant=self.tenant,name="Sem terceira vaga")

    def test_existing_professional_can_be_edited_and_inactivated(self):
        self.first.name="Nome atualizado"
        self.first.save()
        self.first.active=False
        self.first.save()
        self.first.refresh_from_db()
        self.assertFalse(self.first.active)

    def test_bulk_create_and_queryset_activation_are_blocked(self):
        with self.assertRaises(ValidationError):
            Professional.objects.bulk_create([Professional(tenant=self.tenant,name="Importação")])
        inactive=Professional.objects.create(tenant=self.tenant,name="Inativo",active=False)
        with self.assertRaises(ValidationError):
            Professional.objects.filter(pk=inactive.pk).update(active=True)
        inactive.active=True
        with self.assertRaises(ValidationError):
            Professional.objects.bulk_update([inactive],["active"])

    def test_inactive_profile_cannot_be_reactivated_without_seat(self):
        inactive=Professional.objects.create(tenant=self.tenant,name="Inativo",active=False)
        inactive.active=True
        with self.assertRaises(ValidationError):
            inactive.save()

    def test_category_change_does_not_bypass_enabled_dental_module(self):
        module,_=Module.objects.get_or_create(slug="dentistry",defaults={"name":"Odonto"})
        TenantModule.objects.create(tenant=self.tenant,module=module,enabled=True)
        self.tenant.category="clinica"
        self.tenant.save()
        with self.assertRaises(ValidationError):
            Professional.objects.create(tenant=self.tenant,name="Tentativa")
