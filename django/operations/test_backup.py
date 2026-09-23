from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase,override_settings
from django.utils import timezone

from accounts.models import User
from operations.backup import verify_database_backup
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
