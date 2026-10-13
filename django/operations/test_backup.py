from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from operations.backup import verify_database_backup, restore_database_backup, _validate_restore_target
from operations.models import Backup


class BackupIntegrityTests(TestCase):
    def test_integrity_verification_detects_valid_backup(self):
        user=User.objects.create_superuser(email="backup@example.com",password="StrongPassword123!")
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.dump"
            path.write_bytes(b"postgres-backup-test")
            import hashlib
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            backup=Backup.objects.create(
                type=Backup.Type.DATABASE,scope="database",status=Backup.Status.COMPLETED,
                destination="test",path=str(path),size_bytes=path.stat().st_size,
                checksum_sha256=digest,started_at=timezone.now(),completed_at=timezone.now(),
            )
            verification=verify_database_backup(backup=backup,user=user)
            self.assertEqual(verification.status,"passed")


class BackupRestoreSafetyTests(TestCase):
    @patch("operations.backup.connection")
    def test_active_database_aliases_and_credentials_are_rejected(self, database):
        database.settings_dict={"NAME":"applanner"}
        for target in (
            "postgresql://other:secret@db:5432/applanner",
            "postgres://localhost/applanner?sslmode=require",
            "postgresql://127.0.0.1/applan%6eer",
            "postgresql://different-server/applanner",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                _validate_restore_target(target)

    @patch("operations.backup.connection")
    def test_libpq_query_overrides_and_invalid_urls_are_rejected(self, database):
        database.settings_dict={"NAME":"applanner"}
        for target in (
            "postgresql://db/restore?dbname=applanner",
            "postgresql://db/restore?dbname=",
            "postgresql://db/restore?host=production",
            "postgresql://db/restore?service=production",
            "postgresql:///restore", "https://db/restore",
            "postgresql://db:bad/restore", "postgresql://db/",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                _validate_restore_target(target)

    @patch("operations.backup.connection")
    @patch("operations.backup.subprocess.run")
    def test_restore_is_atomic_and_fails_closed_on_existing_objects(self, run, database):
        database.settings_dict={"NAME":"applanner"}
        run.return_value.returncode=0
        import hashlib
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/"test.dump";path.write_bytes(b"test")
            backup=Backup.objects.create(type=Backup.Type.DATABASE,scope="database",
                status=Backup.Status.COMPLETED,destination="test",path=str(path),
                checksum_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),started_at=timezone.now())
            self.assertTrue(restore_database_backup(backup=backup,
                target_url="postgresql://db/applanner_restore?sslmode=require",confirm=True))
            command=run.call_args.args[0]
            self.assertIn("--exit-on-error",command)
            self.assertIn("--single-transaction",command)
            self.assertNotIn("--clean",command)
            run.return_value.returncode=1;run.return_value.stderr="already exists"
            with self.assertRaises(RuntimeError):
                restore_database_backup(backup=backup,target_url="postgresql://db/applanner_restore",confirm=True)

    @patch("operations.backup.subprocess.run")
    def test_confirmation_required_before_restore(self, run):
        with self.assertRaises(ValueError):
            restore_database_backup(backup=None,target_url="postgresql://db/restored")
        run.assert_not_called()
