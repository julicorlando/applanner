from django.test import TestCase

from accounts.models import User


class AppInstallBannerTests(TestCase):
    def test_banner_only_for_people_logged_in(self):
        self.assertNotContains(self.client.get("/account/login/"), "data-app-install-strip")
        user = User.objects.create_user(email="banner@example.test", password="StrongPassword123!")
        self.client.force_login(user)
        page = self.client.get("/legal/privacidade/meus-dados/")
        self.assertContains(page, "data-app-install-strip")
        self.assertContains(page, "Baixar o app")
