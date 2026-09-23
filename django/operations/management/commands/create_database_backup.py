from django.core.management.base import BaseCommand
from operations.backup import create_database_backup


class Command(BaseCommand):
    help="Cria um backup real do PostgreSQL usando pg_dump."

    def handle(self,*args,**options):
        backup=create_database_backup()
        self.stdout.write(self.style.SUCCESS(
            f"Backup #{backup.pk} concluído: {backup.path} ({backup.size_bytes} bytes)"
        ))
