from django.test import TestCase
from django.urls import reverse


class HomeLivePreviewTests(TestCase):
    def test_public_home_labels_real_product_capture_as_demonstration(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "premium-dashboard-demo")
        self.assertContains(response, "dados fictícios de demonstração")
        self.assertContains(response, 'width="1440" height="1000"')
        self.assertNotContains(response, "home-live-preview.")
