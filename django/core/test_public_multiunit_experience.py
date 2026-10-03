from datetime import time
from decimal import Decimal

from django.test import TestCase
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
