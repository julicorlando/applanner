from django.core.cache import cache
from django.test import TestCase

from accounts.models import User

from .models import HomologationRun,OperationalIncident
from .services import record_incident,run_homologation


class OperationsTests(TestCase):
    def test_incident_fingerprint_deduplicates(self):
        first=record_incident(
            category="application",severity=OperationalIncident.Severity.WARNING,
            title="Mesmo problema",details="primeiro",
        )
        second=record_incident(
            category="application",severity=OperationalIncident.Severity.CRITICAL,
            title="Mesmo problema",details="segundo",
        )
        self.assertEqual(first.pk,second.pk)
        second.refresh_from_db()
        self.assertEqual(second.occurrence_count,2)
        self.assertEqual(second.severity,OperationalIncident.Severity.CRITICAL)

    def test_homologation_persists_result(self):
        user=User.objects.create_superuser(email="master@example.com",password="StrongPassword!123")
        run=run_homologation(user=user)
        self.assertIn(run.status,{HomologationRun.Status.PASSED,HomologationRun.Status.WARNING,HomologationRun.Status.BLOCKED})
        self.assertIn("database",run.results)
        self.assertIn("cache",run.results)
