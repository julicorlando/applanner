from django.core.cache import cache
from django.test import TestCase

from accounts.models import User

from .models import HomologationRun,LegacyFailedJobArchive,LegacyMigrationRecord,LegacyRuntimeJob,OperationalIncident
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


class LegacyRuntimeArchiveTests(TestCase):
    def test_legacy_runtime_history_is_preserved_without_execution(self):
        job=LegacyRuntimeJob.objects.create(
            type="marketing.lead_email",payload_encrypted="ciphertext",status="completed",
            attempts=1,available_at="2026-09-23T10:00:00Z",
            created_at="2026-09-23T10:00:00Z",updated_at="2026-09-23T10:01:00Z",
        )
        failed=LegacyFailedJobArchive.objects.create(
            type="marketing.lead_email",payload_encrypted="ciphertext",status="failed",
            attempts=3,available_at="2026-09-23T10:00:00Z",failed_at="2026-09-23T10:05:00Z",
            created_at="2026-09-23T10:00:00Z",updated_at="2026-09-23T10:05:00Z",
        )
        migration=LegacyMigrationRecord.objects.create(
            migration="047_email_marketing_campaign_redispatch.sql",batch=1,
            executed_at="2026-09-23T10:00:00Z",
        )
        self.assertEqual(job.type,"marketing.lead_email")
        self.assertEqual(failed.status,"failed")
        self.assertEqual(migration.batch,1)

    def test_importer_covers_legacy_runtime_tables(self):
        from core.management.commands.import_legacy_specialized import SPECS
        mapping={item["table"]:item["model"] for item in SPECS}
        self.assertEqual(mapping["jobs"],"operations.LegacyRuntimeJob")
        self.assertEqual(mapping["jobs_failed_archive"],"operations.LegacyFailedJobArchive")
        self.assertEqual(mapping["migrations"],"operations.LegacyMigrationRecord")
