from datetime import time
from decimal import Decimal

from django.test import TestCase
from django.templatetags.static import static
from django.urls import reverse

from contenthub.models import PublicReview
from engagement.models import ServicePackage
from tenants.models import Tenant,Unit,UnitBusinessHours


class PublicMultiunitExperienceTests(TestCase):
    def setUp(self):
        self.tenant=Tenant.objects.create(
            name="Rede Pública",slug="rede-publica",public_slug="rede-publica",
            public_enabled=True,public_booking_enabled=True,status=Tenant.Status.ACTIVE,
            timezone="America/Recife",
        )
        self.first=Unit.objects.create(
            tenant=self.tenant,name="Centro",is_primary=True,active=True,
            latitude=Decimal("-7.8500000"),longitude=Decimal("-35.2500000"),
            amenities=["Wi-Fi","Estacionamento"],payment_methods=["Pix","Cartão"],
            instagram="https://instagram.com/redepublica",
        )
        self.second=Unit.objects.create(
            tenant=self.tenant,name="Bairro",active=True,
            latitude=Decimal("-7.8600000"),longitude=Decimal("-35.2600000"),
        )
        UnitBusinessHours.objects.create(
            tenant=self.tenant,unit=self.first,weekday=1,
            opens_at=time(8),closes_at=time(18),active=True,
        )
        ServicePackage.objects.create(
            tenant=self.tenant,name="Pacote 4 visitas",price=Decimal("100.00"),
            validity_days=30,active=True,recurring=False,
        )
        ServicePackage.objects.create(
            tenant=self.tenant,name="Clube mensal",price=Decimal("79.90"),
            validity_days=30,active=True,recurring=True,
        )
        PublicReview.objects.create(
            tenant=self.tenant,customer_name="Cliente",rating=5,
            comment="Comentário privado na capa",active=True,
        )

    def test_public_page_exposes_multiunit_metadata_without_review_comment(self):
        response=self.client.get(reverse("tenant-public",args=[self.tenant.public_slug]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Comodidades")
        self.assertContains(response,"Formas de pagamento")
        self.assertContains(response,"Funcionamento")
        self.assertContains(response,"Assinaturas")
        self.assertContains(response,"Pacotes")
        self.assertContains(response,"Cliente")
        self.assertNotContains(response,"Comentário privado na capa")
        self.assertContains(response,'data-unit-card="'+str(self.first.pk)+'"')
        self.assertContains(response,"navigator.geolocation")

    def test_public_week_includes_missing_and_explicitly_closed_days(self):
        UnitBusinessHours.objects.create(
            tenant=self.tenant,unit=self.first,weekday=7,closed=True,active=True,
        )
        response=self.client.get(reverse("tenant-public",args=[self.tenant.public_slug]))
        hours=response.context["units"][0].public_hours
        self.assertEqual(len(hours),7)
        self.assertFalse(hours[0]["not_configured"])
        self.assertTrue(hours[1]["not_configured"])
        self.assertTrue(hours[6]["closed"])
        self.assertEqual(sum(row["is_today"] for row in hours),1)
        self.assertContains(response,"Não informado")
        self.assertContains(response,"Fechado")

    def test_single_unit_has_no_switch_control_and_one_service_catalog(self):
        from scheduling.models import Service
        self.second.active=False
        self.second.save(update_fields=["active"])
        service=Service.objects.create(tenant=self.tenant,name="Corte de cabelo",duration_minutes=30,price=35)
        response=self.client.get(reverse("tenant-public",args=[self.tenant.public_slug]))
        self.assertNotContains(response,"Escolher outra unidade")
        self.assertContains(response,'data-select-service="'+str(service.pk)+'"',count=1)
        self.assertContains(response,'class="topbar public-header"')
        self.assertContains(response,static('js/public-booking.js'))
        self.assertContains(response,'data-duration="30"')

    def test_public_header_stays_client_focused_for_signed_in_master(self):
        from accounts.models import User
        master=User.objects.create_user(email="public-review@example.test",password="test-only",is_superuser=True,is_staff=True)
        self.client.force_login(master)
        response=self.client.get(reverse("tenant-public",args=[self.tenant.public_slug]))
        self.assertEqual(response.status_code,200)
        html=response.content.decode()
        header=html.split('<header',1)[1].split('</header>',1)[0]
        self.assertNotIn('/master/',header)
        self.assertNotIn('/admin/',header)
        self.assertIn('Localização e contato',header)
        self.assertIn('theme-toggle',header)
