import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


TASKS=[
    ("Processar notificações","communications.tasks.process_notification_queue",1,"minutes"),
    ("Processar e-mail marketing","communications.tasks.process_marketing_deliveries",1,"minutes"),
    ("Gerar lembretes de agenda","scheduling.tasks.queue_appointment_reminders",5,"minutes"),
    ("Gerar reservas de mensalistas Arena","arena.tasks.generate_due_memberships",6,"hours"),
    ("Expirar sinais Arena","arena.tasks.expire_unpaid_reservations",5,"minutes"),
    ("Cobrar mensalidades de pacotes","engagement.tasks.bill_due_memberships",6,"hours"),
    ("Expirar pacotes e waitlist","engagement.tasks.expire_packages_and_waitlist",6,"hours"),
    ("Atualizar inteligência de retorno","engagement.tasks.refresh_behavior_intelligence",12,"hours"),
    ("Processar CRM automotivo","auto.tasks.process_auto_crm",1,"hours"),
    ("Aplicar retenção LGPD de leads","commercial.tasks.enforce_lead_retention",24,"hours"),
    ("Expirar checkouts","billing.tasks.expire_checkouts",10,"minutes"),
    ("Reconciliar assinaturas","billing.tasks.reconcile_subscription_states",1,"hours"),
    ("Health check operacional","operations.tasks.platform_health_check",5,"minutes"),
    ("Processar conversões Meta","growth.tasks.process_meta_conversion_queue",1,"minutes"),
    ("Atualizar métricas Arena","arena.tasks.refresh_arena_customer_metrics",12,"hours"),
    ("Backup diário do PostgreSQL","operations.tasks.scheduled_database_backup",24,"hours"),
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
