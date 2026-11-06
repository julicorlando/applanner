from django.core.management.base import BaseCommand,CommandError
from operations.backup import restore_database_backup
from operations.models import Backup


class Command(BaseCommand):
    help="Restaura um backup em um BANCO DE DESTINO separado."

    def add_arguments(self,parser):
        parser.add_argument("backup_id",type=int)
        parser.add_argument("--database-url",required=True,dest="database_url")
        parser.add_argument("--confirm-restore",action="store_true")

    def handle(self,*args,**options):
        if not options["confirm_restore"]:
            raise CommandError("Use --confirm-restore para confirmar.")
        try:
            backup=Backup.objects.get(pk=options["backup_id"])
            restore_database_backup(
                backup=backup,target_url=options["database_url"],confirm=True
            )
        except (Backup.DoesNotExist,ValueError,RuntimeError) as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS("Restauração concluída no banco de destino."))
