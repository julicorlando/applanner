import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


TASKS=[
    ("Processar notificações","communications.tasks.process_notification_queue",1,"minutes"),
    ("Processar e-mail marketing","communications.tasks.process_marketing_deliveries",1,"minutes"),
    ("Gerar lembretes de agenda","scheduling.tasks.queue_appointment_reminders",5,"minutes"),
    ("Gerar reservas de mensalistas Arena","arena.tasks.generate_due_memberships",6,"hours"),
]


class Command(BaseCommand):
    help="Sincroniza tarefas periódicas padrão do ApPlanner."

    def handle(self,*args,**options):
        for name,task,every,period in TASKS:
            schedule,_=IntervalSchedule.objects.get_or_create(every=every,period=period)
            PeriodicTask.objects.update_or_create(
                name=name,
                defaults={
                    "task":task,
                    "interval":schedule,
                    "enabled":True,
                    "args":json.dumps([]),
                    "kwargs":json.dumps({}),
                },
            )
        self.stdout.write(self.style.SUCCESS(f"{len(TASKS)} tarefas periódicas sincronizadas."))
