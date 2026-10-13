from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse
from accounts.models import User
from contenthub.models import PlatformHomepage, PublicReview
from tenants.models import Tenant, Unit
from core.workspace import navigation


class PremiumExperienceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Salão Aurora",
            slug="premium-aurora",
            category="salao",
            public_enabled=True,
            public_booking_enabled=True,
            status="active",
        )
        self.unit = Unit.objects.create(
            tenant=self.tenant,
            name="Centro",
            city="Recife",
            postal_code="50000-001",
            latitude=-8.05,
            longitude=-34.9,
            is_primary=True,
        )
        self.second = Unit.objects.create(
            tenant=self.tenant,
            name="Praia",
            city="Olinda",
            postal_code="53000001",
            latitude=-8.02,
            longitude=-34.88,
        )
        self.owner = User.objects.create_user(
            email="owner@premium.test", tenant=self.tenant, role="owner"
        )

    def request(self, path="/app/", user=None, locked=False):
        request = RequestFactory().get(path)
        request.user = user or self.owner
        request.session = {}
        request.billing_locked = locked
        return request

    def test_public_pages_never_receive_private_navigation(self):
        self.assertEqual(navigation(self.request("/directory/")), {})
        self.assertEqual(navigation(self.request("/p/premium-aurora/")), {})
        self.assertEqual(navigation(self.request(user=AnonymousUser())), {})

    def test_locked_subscription_only_exposes_payment(self):
        groups = navigation(self.request(locked=True))["workspace_groups"]
        self.assertEqual(
            [item["url"] for group in groups for item in group["items"]],
            [reverse("billing-subscription-status")],
        )

    def test_professional_cannot_receive_management_links(self):
        pro = User.objects.create_user(
            email="pro@premium.test", tenant=self.tenant, role="professional"
        )
        groups = navigation(self.request(user=pro))["workspace_groups"]
        self.assertEqual(
            [item["url"] for group in groups for item in group["items"]],
            [reverse("professional-area")],
        )

    def test_directory_search_selects_specific_unit_and_handles_accents(self):
        response = self.client.get(reverse("public-directory"), {"q": "olinda"})
        self.assertEqual(
            [row["unit"].pk for row in response.context["cards"]], [self.second.pk]
        )
        response = self.client.get(reverse("public-directory"), {"q": "salao"})
        self.assertEqual(len(response.context["cards"]), 2)
        response = self.client.get(reverse("public-directory"), {"q": "50000001"})
        self.assertEqual(
            [row["unit"].pk for row in response.context["cards"]], [self.unit.pk]
        )

    def test_directory_rating_is_based_only_on_published_reviews(self):
        PublicReview.objects.create(
            tenant=self.tenant,
            customer_name="Pessoa",
            rating=5,
            comment="Ótimo",
            active=True,
        )
        PublicReview.objects.create(
            tenant=self.tenant,
            customer_name="Privado",
            rating=1,
            comment="Privado",
            active=False,
        )
        response = self.client.get(reverse("public-directory"), {"rating": "5"})
        self.assertEqual(len(response.context["cards"]), 2)
        self.assertEqual(response.context["cards"][0]["rating"]["total"], 1)
        self.assertContains(response, "avaliações da empresa")
        self.assertNotContains(response, "Privado")

    def test_directory_no_reviews_is_not_five_stars(self):
        response = self.client.get(reverse("public-directory"), {"rating": "5"})
        self.assertEqual(response.context["cards"], [])

    def test_directory_distance_cannot_exceed_existing_thirty_km_limit(self):
        far = Unit.objects.create(
            tenant=self.tenant, name="Distante", latitude=-8.5, longitude=-34.9
        )
        response = self.client.get(
            reverse("public-directory"),
            {"lat": "-8.05", "lon": "-34.9", "radius": "999"},
        )
        self.assertEqual(response.context["radius"], 30)
        self.assertNotIn(far.pk, [row["unit"].pk for row in response.context["cards"]])

    def test_directory_medical_visibility_follows_master_configuration(self):
        medical = Tenant.objects.create(
            name="Clínica",
            slug="premium-medical",
            category="medico",
            public_enabled=True,
            status="active",
        )
        Unit.objects.create(tenant=medical, name="Consultório")
        platform = PlatformHomepage.objects.create(pk=1, medical_segment_visible=False)
        response = self.client.get(reverse("public-directory"))
        self.assertNotIn(
            medical.pk, [row["tenant"].pk for row in response.context["cards"]]
        )
        platform.medical_segment_visible = True
        platform.save()
        response = self.client.get(reverse("public-directory"), {"segment": "saude"})
        self.assertEqual(
            [row["tenant"].pk for row in response.context["cards"]], [medical.pk]
        )
