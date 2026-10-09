"""Serialize release initialization before exposing HTTP or starting jobs."""
import time
from contextlib import contextmanager

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


# Session advisory lock shared by all application releases in this database.
BOOTSTRAP_LOCK_KEY=0x4150504C414E4E52
BOOTSTRAP_COMMANDS=(
    "migrate", "seed_modules", "seed_sales_plans", "seed_rbac",
    "seed_periodic_tasks", "collectstatic",
)


@contextmanager
def release_initialization_lock(timeout):
    default=connections["default"]
    if default.vendor == "sqlite":
        # Local development/tests; PostgreSQL is the supported deployment engine.
        yield
        return
    if default.vendor != "postgresql":
        raise CommandError("Inicialização protegida exige PostgreSQL em produção.")
    # A separate SESSION retains the lock when migrations commit or change transactions.
    lock_connection=default.copy(alias="bootstrap_release_lock")
    try:
        lock_connection.ensure_connection()
        deadline=time.monotonic()+timeout
        while True:
            with lock_connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)",[BOOTSTRAP_LOCK_KEY])
                acquired=cursor.fetchone()[0]
            if acquired:
                break
            remaining=deadline-time.monotonic()
            if remaining <= 0:
                raise CommandError("Tempo esgotado aguardando outra inicialização. Nenhuma migration foi iniciada.")
            time.sleep(min(0.5,remaining))
        yield
    finally:
        # PostgreSQL releases session locks on disconnect, including command failures.
        lock_connection.close()


class Command(BaseCommand):
    help="Aplica migrations/seeds/static com exclusão mútua entre releases PostgreSQL."

    def add_arguments(self,parser):
        parser.add_argument("--lock-timeout",type=int,default=120)

    def handle(self,*args,**options):
        timeout=options["lock_timeout"]
        if not 1 <= timeout <= 3600:
            raise CommandError("--lock-timeout deve estar entre 1 e 3600 segundos.")
        with release_initialization_lock(timeout):
            for name in BOOTSTRAP_COMMANDS:
                kwargs={"verbosity":options["verbosity"]}
                if name in {"migrate","collectstatic"}:
                    kwargs["interactive"]=False
                call_command(name,**kwargs)
