import re
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from billing.models import Plan,Subscription
from scheduling.models import Professional,ProfessionalAvailability,Service
from .models import Tenant,TenantOnboarding,Unit


class FirstAccessTests(TestCase):
    def setUp(self):
        self.plan=Plan.objects.create(
            name="Inicial",slug="onboarding-plan",monthly_price=Decimal("39.90"),
            trial_days=7,trial_without_card=True,active=True,public_visible=True,
        )

    def signup(self):
        response=self.client.post("/cadastro/",{
            "plan":self.plan.pk,"billing_cycle":Subscription.BillingCycle.MONTHLY,
            "business_name":"Novo Espaço","category":"barbearia","owner_name":"Responsável",
            "email":"first-owner@example.com","phone":"81999999999",
            "password":"StrongPassword!123","password_confirm":"StrongPassword!123",
        })
        self.assertRedirects(response,"/inicio/")
        return User.objects.get(email="first-owner@example.com")

    def test_guided_flow_guards_private_data_and_requires_verified_email(self):
        owner=self.signup()
        tenant=owner.tenant
        other=Tenant.objects.create(name="Outro",slug="outro")
        self.assertTrue(TenantOnboarding.objects.get(tenant=tenant).required)
        self.assertRedirects(self.client.get("/"),"/inicio/")
        self.assertRedirects(self.client.get("/app/"),"/inicio/")
        self.assertRedirects(self.client.post("/app/agenda/servicos/novo/",{"name":"Invasão"}),"/inicio/")
        self.assertEqual(Service.objects.count(),0)
        self.assertEqual(self.client.get(f"/p/{tenant.slug}/").status_code,404)

        company={"name":"Novo Espaço","document":"529.982.247-25","category":"barbearia",
                 "email":"first-owner@example.com","phone":"(81) 99999-9999","description":"Barbearia",
                 "tenant":other.pk}
        bad=self.client.post("/inicio/",{**company,"document":"11111111111"})
        self.assertContains(bad,"CPF ou CNPJ válido")
        self.assertRedirects(self.client.post("/inicio/",company),"/inicio/")
        self.assertEqual(Tenant.objects.get(pk=tenant.pk).document,"52998224725")
        self.assertEqual(Tenant.objects.get(pk=other.pk).document,"")
        unit={"name":"Unidade Centro","postal_code":"55100-000","address":"Rua Principal",
              "address_number":"10","district":"Centro","city":"Carpina","state":"PE",
              "phone":"81999999999","whatsapp":"81988888888","tenant":other.pk}
        self.assertRedirects(self.client.post("/inicio/",unit),"/inicio/")
        self.assertEqual(Unit.objects.get(tenant=tenant).city,"Carpina")
        self.assertEqual(Unit.objects.filter(tenant=other).count(),0)
        self.assertRedirects(self.client.post("/inicio/",{
            "name":"Corte","description":"","duration_minutes":"30","price":"35.00","tenant":other.pk,
        }),"/inicio/")
        self.assertEqual(Service.objects.get().tenant,tenant)
        self.assertRedirects(self.client.post("/inicio/",{
            "name":"Barbeiro","specialty":"Cortes","phone":"","email":"","tenant":other.pk,
        }),"/inicio/")
        self.assertEqual(Professional.objects.get().unit.tenant,tenant)
        self.assertContains(self.client.post("/inicio/",{
            "days":["1","2"],"start_time":"18:00","end_time":"09:00",
        }),"depois da abertura")
        self.assertRedirects(self.client.post("/inicio/",{
            "days":["1","2"],"start_time":"09:00","end_time":"18:00",
        }),"/inicio/")
        self.assertEqual(ProfessionalAvailability.objects.filter(tenant=tenant,active=True).count(),2)
        self.assertRedirects(self.client.post("/inicio/",{
            "methods":["pix","card"],"primary_color":"#123456","public_headline":"Agende agora",
            "public_subheadline":"Cortes","public_booking_enabled":"on","public_enabled":"on",
        }),"/inicio/")
        tenant.refresh_from_db()
        self.assertFalse(tenant.public_enabled)
        self.assertEqual(tenant.accepted_payment_methods,["pix","card"])
        self.client.post("/inicio/",{"publish":"on"})
        self.assertFalse(TenantOnboarding.objects.get(tenant=tenant).completed_at)
        self.client.post("/account/verification/send/")
        self.assertEqual(len(mail.outbox),1)
        token=re.search(r"/account/verify-email/([^/]+)/",mail.outbox[0].body).group(1)
        self.client.get(f"/account/verify-email/{token}/")
        self.assertRedirects(self.client.post("/inicio/",{"publish":"on"}),"/")
        tenant.refresh_from_db()
        self.assertTrue(tenant.public_enabled)
        self.assertIsNotNone(TenantOnboarding.objects.get(tenant=tenant).completed_at)
        self.assertEqual(self.client.get("/").status_code,200)

    def test_other_users_cannot_finish_onboarding_and_existing_tenants_unchanged(self):
        owner=self.signup()
        staff=User.objects.create_user(email="staff-first@example.com",password="StrongPassword!123",
            tenant=owner.tenant,role="reception")
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/inicio/").status_code,403)
        self.assertRedirects(self.client.post("/app/agenda/servicos/novo/",{}),"/inicio/",fetch_redirect_response=False)
        legacy=Tenant.objects.create(name="Legado",slug="legado")
        TenantOnboarding.objects.create(tenant=legacy,company_done=False,required=False)
        staff.tenant=legacy
        staff.save(update_fields=["tenant"])
        self.assertNotEqual(self.client.get("/").status_code,302)

    def test_login_does_not_redirect_to_external_host(self):
        user=User.objects.create_user(email="safe-login@example.com",password="StrongPassword!123")
        response=self.client.post("/account/login/?next=https://example.com/steal",{
            "email":user.email,"password":"StrongPassword!123",
        })
        self.assertRedirects(response,"/",fetch_redirect_response=False)
