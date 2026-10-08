from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from core.management.commands.bootstrap_application import (
    BOOTSTRAP_COMMANDS, BOOTSTRAP_LOCK_KEY, Command, release_initialization_lock,
)


class ReleaseBootstrapTests(SimpleTestCase):
    def command(self,timeout=120):
        Command().handle(lock_timeout=timeout,verbosity=0)

    @patch("core.management.commands.bootstrap_application.connections")
    @patch("core.management.commands.bootstrap_application.call_command")
    def test_sqlite_fallback_runs_commands_in_order(self,call,connections):
        connections["default"].vendor="sqlite"
        self.command()
        self.assertEqual([item.args[0] for item in call.call_args_list],list(BOOTSTRAP_COMMANDS))
        self.assertFalse(call.call_args_list[0].kwargs["interactive"])
        self.assertFalse(call.call_args_list[-1].kwargs["interactive"])
        connections["default"].copy.assert_not_called()

    @patch("core.management.commands.bootstrap_application.connections")
    @patch("core.management.commands.bootstrap_application.call_command")
    def test_postgres_lock_uses_dedicated_session_and_covers_all_commands(self,call,connections):
        connections["default"].vendor="postgresql"
        locked=connections["default"].copy.return_value
        cursor=locked.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value=(True,)
        def assert_held(*args,**kwargs):
            locked.close.assert_not_called()
        call.side_effect=assert_held
        self.command()
        cursor.execute.assert_called_once_with("SELECT pg_try_advisory_lock(%s)",[BOOTSTRAP_LOCK_KEY])
        locked.close.assert_called_once()
        self.assertEqual(call.call_count,len(BOOTSTRAP_COMMANDS))

    @patch("core.management.commands.bootstrap_application.connections")
    @patch("core.management.commands.bootstrap_application.call_command",side_effect=RuntimeError("migration failed"))
    def test_failure_stops_seeds_and_releases_session(self,call,connections):
        connections["default"].vendor="postgresql"
        locked=connections["default"].copy.return_value
        locked.cursor.return_value.__enter__.return_value.fetchone.return_value=(True,)
        with self.assertRaises(RuntimeError):
            self.command()
        call.assert_called_once_with("migrate",verbosity=0,interactive=False)
        locked.close.assert_called_once()

    @patch("core.management.commands.bootstrap_application.time.sleep")
    @patch("core.management.commands.bootstrap_application.time.monotonic",side_effect=[0,1,2])
    @patch("core.management.commands.bootstrap_application.connections")
    @patch("core.management.commands.bootstrap_application.call_command")
    def test_timeout_never_starts_migrations(self,call,connections,clock,sleep):
        connections["default"].vendor="postgresql"
        locked=connections["default"].copy.return_value
        locked.cursor.return_value.__enter__.return_value.fetchone.return_value=(False,)
        with self.assertRaises(CommandError):
            self.command(timeout=2)
        call.assert_not_called()
        sleep.assert_called_once_with(0.5)
        locked.close.assert_called_once()

    @patch("core.management.commands.bootstrap_application.call_command")
    def test_invalid_timeout_never_starts_migrations(self,call):
        for timeout in (0,-1,3601):
            with self.subTest(timeout=timeout), self.assertRaises(CommandError):
                self.command(timeout)
        call.assert_not_called()
