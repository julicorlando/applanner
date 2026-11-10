from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SECURE_SSL_REDIRECT=True, ALLOWED_HOSTS=["127.0.0.1"])
class ProductionHealthcheckTests(TestCase):
    def test_internal_probe_reaches_health_checks_without_redirect(self):
        response=self.client.get(reverse("healthz"),HTTP_HOST="127.0.0.1",HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["checks"],{"database":True,"cache":True})

    @patch("core.views.cache.set",side_effect=RuntimeError("cache unavailable"))
    def test_degraded_cache_fails_probe_instead_of_returning_redirect(self,_set):
        response=self.client.get(reverse("healthz"),HTTP_HOST="127.0.0.1",HTTP_X_FORWARDED_PROTO="https")
        self.assertEqual(response.status_code,503)
        self.assertFalse(response.json()["checks"]["cache"])
