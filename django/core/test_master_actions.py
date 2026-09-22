from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from operations.models import HomologationRun


class MasterOperationalActionTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser(email="master-actions@example.com",password="StrongPassword123!")
        self.client.force_login(self.user)

    @patch("operations.services.shutil.disk_usage")
    def test_homologation_action(self,disk_usage):
        disk_usage.return_value=type("Usage",(),{"free":20*1024*1024*1024})()
        response=self.client.post(reverse("master-operational-action",args=["homologation-run"]))
        self.assertEqual(response.status_code,302)
        self.assertEqual(HomologationRun.objects.count(),1)
