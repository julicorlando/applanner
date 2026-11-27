"""Verify the real worker import path without imports from the test suite."""

import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class WorkerTaskRegistrationTests(SimpleTestCase):
    def test_every_seeded_periodic_task_is_registered_on_cold_worker_start(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from applanner.celery import app; "
                "app.loader.import_default_modules(); "
                "from core.management.commands.seed_periodic_tasks import TASKS; "
                "missing = sorted({row[1] for row in TASKS} - set(app.tasks)); "
                "assert not missing, f'Unregistered periodic tasks: {missing}'",
            ],
            cwd=settings.BASE_DIR,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
