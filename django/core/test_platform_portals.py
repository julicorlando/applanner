from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from commercial.models import CommercialProfile,Lead


class PlatformPortalAccessTests(TestCase):
    def test_master_requires_superuser(self):
        user=User.objects.create_user(email="user@example.com",password="StrongPassword123!")
        self.client.force_login(user)
        response=self.client.get(reverse("master-home"))
        self.assertEqual(response.status_code,403)

    def test_superuser_can_open_master(self):
        user=User.objects.create_superuser(email="root@example.com",password="StrongPassword123!")
        self.client.force_login(user)
        response=self.client.get(reverse("master-home"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'id="master-function-search"')
        self.assertContains(response,'data-master-function')
        self.assertContains(response,'class="shortcut-grid master-category-grid"')
        self.assertContains(response,'js/master-functions')

    def test_commercial_profile_can_open_queue(self):
        user=User.objects.create_user(email="sales@example.com",password="StrongPassword123!")
        CommercialProfile.objects.create(user=user,active=True)
        Lead.objects.create(name="Cliente",phone="81999999999",email="client@example.com",business_type="Barbearia")
        self.client.force_login(user)
        response=self.client.get(reverse("commercial-dashboard"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Cliente")
