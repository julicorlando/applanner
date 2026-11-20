from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from finance.models import ProfessionalCommission
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant


class ProfessionalAreaTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(name="Barbearia A",slug="barbearia-a",status=Tenant.Status.ACTIVE)
        self.other=Tenant.objects.create(name="Barbearia B",slug="barbearia-b",status=Tenant.Status.ACTIVE)
        self.owner=User.objects.create_user(email="dono@example.test",password="StrongPassword123!",
                                            tenant=self.tenant,role="owner")
        self.professional=Professional.objects.create(tenant=self.tenant,name="Ana",
                                                       email="ana@example.test",commission_percent=Decimal("40"))
        self.other_professional=Professional.objects.create(tenant=self.tenant,name="Bia")

    def test_owner_creates_account_and_professional_sees_only_own_data(self):
        self.client.force_login(self.owner)
        response=self.client.post(reverse("professional-access",args=[self.professional.pk]),{
            "email":"ana@example.test","password1":"TemporaryPassword2026!",
            "password2":"TemporaryPassword2026!","enabled":"on",
        })
        self.assertEqual(response.status_code,302)
        professional=Professional.objects.get(pk=self.professional.pk)
        user=professional.user
        self.assertEqual(user.role,"professional")
        self.assertTrue(user.must_change_password)
        self.assertEqual(user.tenant,self.tenant)
        self.assertTrue(user.check_password("TemporaryPassword2026!"))
        service=Service.objects.create(tenant=self.tenant,name="Corte",duration_minutes=30,price=Decimal("80"))
        start=timezone.now()+timedelta(days=1)
        for professional,name in [(self.professional,"Cliente próprio"),(self.other_professional,"Cliente de Bia")]:
            customer=Customer.objects.create(tenant=self.tenant,name=name)
            Appointment.objects.create(tenant=self.tenant,professional=professional,
                                       customer=customer,service=service,starts_at=start,
                                       ends_at=start+timedelta(minutes=30),status=Appointment.Status.CONFIRMED,
                                       service_price_snapshot=Decimal("80"))
        ProfessionalCommission.objects.create(tenant=self.tenant,professional=self.professional,
                                                source_type="test",source_id=1,gross_amount=Decimal("80"),
                                                commission_amount=Decimal("32"),status=ProfessionalCommission.Status.PAID)
        user.must_change_password=False
        user.save(update_fields=["must_change_password"])
        self.client.force_login(user)
        response=self.client.get(reverse("professional-area"))
        self.assertContains(response,"Cliente próprio")
        self.assertNotContains(response,"Cliente de Bia")
        self.assertContains(response,"32,00")
        self.assertEqual(response.context["projected_commission"],Decimal("32"))
        self.assertRedirects(self.client.get("/"),reverse("professional-area"))
        self.assertEqual(self.client.get(reverse("portal-resource-list",args=["agenda","clientes"])).status_code,403)

    def test_other_tenant_cannot_manage_professional_and_existing_email_is_rejected(self):
        self.client.force_login(self.owner)
        someone_else=Professional.objects.create(tenant=self.other,name="De outra empresa")
        self.assertEqual(self.client.get(reverse("professional-access",args=[someone_else.pk])).status_code,404)
        User.objects.create_user(email="taken@example.test",password="StrongPassword123!",tenant=self.other)
        response=self.client.post(reverse("professional-access",args=[self.professional.pk]),{
            "email":"taken@example.test","password1":"TemporaryPassword2026!",
            "password2":"TemporaryPassword2026!","enabled":"on",
        })
        self.assertContains(response,"já pertence a outra conta")
        self.professional.refresh_from_db()
        self.assertIsNone(self.professional.user_id)

    def test_reception_cannot_create_access_and_disabling_revokes_sessions(self):
        reception=User.objects.create_user(email="recepcao@example.test",password="StrongPassword123!",
                                           tenant=self.tenant,role="reception")
        self.client.force_login(reception)
        self.assertEqual(self.client.get(reverse("professional-access",args=[self.professional.pk])).status_code,403)
        professional_user=User.objects.create_user(email="ana@example.test",password="StrongPassword123!",
                                                    tenant=self.tenant,role="professional")
        self.professional.user=professional_user
        self.professional.save(update_fields=["user"])
        self.client.force_login(self.owner)
        response=self.client.post(reverse("professional-access",args=[self.professional.pk]),{
            "email":"ana@example.test","password1":"","password2":"",
        })
        self.assertEqual(response.status_code,302)
        professional_user.refresh_from_db()
        self.assertFalse(professional_user.is_active)
        self.assertEqual(professional_user.session_version,2)

    def test_platform_and_tenant_dashboards_show_shortcuts(self):
        self.client.force_login(self.owner)
        response=self.client.get("/")
        self.assertContains(response,"Novo agendamento")
        self.assertContains(response,"Equipe e acessos")
        self.client.logout()
        master=User.objects.create_superuser(email="master@example.test",password="StrongPassword123!")
        self.client.force_login(master)
        response=self.client.get("/")
        self.assertContains(response,"Gerenciar estabelecimentos")
        self.assertContains(response,"Leads recentes")
