from django.apps import apps
from django.core.management.base import BaseCommand
from django.core.management.color import no_style
from django.db import connection, transaction


class Command(BaseCommand):
    help="Reposiciona sequences do PostgreSQL após importar IDs explícitos do legado."

    def handle(self,*args,**options):
        statements=connection.ops.sequence_reset_sql(no_style(),apps.get_models())
        if not statements:
            self.stdout.write("Nenhuma sequence precisa ser ajustada neste banco.")
            return
        with transaction.atomic(), connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        self.stdout.write(self.style.SUCCESS(
            f"{len(statements)} sequence(s) reposicionada(s) após a migração."
        ))
