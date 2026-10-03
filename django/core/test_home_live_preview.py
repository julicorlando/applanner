from django.test import TestCase
from django.urls import reverse


class HomeLivePreviewTests(TestCase):
    def test_public_home_renders_animated_schedule_preview(self):
        response=self.client.get(reverse("home"))

        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Demonstração ao vivo")
        self.assertContains(response,'data-live-preview')
        self.assertContains(response,"home-live-preview.")
        self.assertContains(response,"Novo cliente")
