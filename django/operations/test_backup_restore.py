"""Opt-in PostgreSQL restore drill for a disposable CI database, never production."""
import os
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import quote
from uuid import uuid4

import psycopg
from psycopg import sql
from django.db import connection
from django.test import TransactionTestCase

from accounts.models import User
from operations.backup import create_database_backup, restore_database_backup


@skipUnless(os.getenv("APPLANNER_BACKUP_RESTORE_SMOKE") == "true", "PostgreSQL restore drill requires explicit CI opt-in")
class PostgreSQLBackupRestoreSmokeTests(TransactionTestCase):
    def test_dump_restores_customer_data_to_disposable_database(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        cfg=connection.settings_dict
        active_name=str(cfg["NAME"])
        if not active_name.startswith("test_"):
            self.fail("Restore smoke must run against Django's isolated test database")
        target_name="applanner_restore_ci_"+uuid4().hex[:16]
        email="restore-proof-"+uuid4().hex+"@example.com"
        User.objects.create_user(email=email,password="RestoreSmokePassword123!")
        target_url="postgresql://{}:{}@{}:{}/{}".format(
            quote(cfg.get("USER") or "",safe=""),
            quote(cfg.get("PASSWORD") or "",safe=""),
            cfg.get("HOST") or "localhost",cfg.get("PORT") or "5432",target_name,
        )
        created=False
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
            created=True
            with TemporaryDirectory() as tmp, patch.dict(os.environ,{"BACKUP_DIR":tmp}):
                backup=create_database_backup()
                self.assertTrue(restore_database_backup(backup=backup,target_url=target_url,confirm=True))
            with psycopg.connect(target_url) as restored:
                row=restored.execute("SELECT email FROM accounts_user WHERE email=%s",(email,)).fetchone()
                self.assertEqual(row,(email,))
                count=restored.execute("SELECT COUNT(*) FROM django_migrations").fetchone()[0]
                self.assertGreater(count,0)
        finally:
            if created:
                with connection.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target_name)))


@skipUnless(os.getenv("APPLANNER_BACKUP_RESTORE_SMOKE") == "true", "PostgreSQL bootstrap lock requires explicit CI opt-in")
class PostgreSQLReleaseLockSmokeTests(TransactionTestCase):
    def test_separate_release_cannot_acquire_lock_across_migration_commits(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        from core.management.commands.bootstrap_application import BOOTSTRAP_LOCK_KEY, release_initialization_lock
        contender=connection.copy(alias="bootstrap_contender")
        try:
            with release_initialization_lock(2):
                # Migrations commit the default connection; dedicated-session lock remains.
                connection.commit()
                with contender.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)",[BOOTSTRAP_LOCK_KEY])
                    self.assertFalse(cursor.fetchone()[0])
            with contender.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)",[BOOTSTRAP_LOCK_KEY])
                self.assertTrue(cursor.fetchone()[0])
        finally:
            contender.close()

    def test_waiting_release_times_out_and_can_start_after_first_session_closes(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL")
        from django.core.management.base import CommandError
        from core.management.commands.bootstrap_application import BOOTSTRAP_LOCK_KEY, release_initialization_lock
        holder=connection.copy(alias="bootstrap_holder")
        try:
            with holder.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_lock(%s)",[BOOTSTRAP_LOCK_KEY])
            with self.assertRaises(CommandError):
                with release_initialization_lock(1):
                    self.fail("Concurrent initialization must not enter")
        finally:
            holder.close()
        with release_initialization_lock(1):
            pass
