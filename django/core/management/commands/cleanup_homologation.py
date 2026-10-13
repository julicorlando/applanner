"""Explicit, reversible cleanup restricted to a named homologation company."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from communications.models import Notification
from core.templatetags.display_pt import homologation_record
from scheduling.models import Appointment, Professional, Service
from tenants.models import Tenant


class Command(BaseCommand):
    help="Desativa cadastros QA e cancela reservas sintéticas futuras, sem excluir histórico. Simulação por padrão."

    def add_arguments(self,parser):
        parser.add_argument("--tenant-slug",required=True)
        parser.add_argument("--apply",action="store_true")

    def handle(self,*args,**options):
        tenant=Tenant.objects.filter(slug=options["tenant_slug"]).first()
        if not tenant or not tenant.name.casefold().startswith("homologação qa"):
            raise CommandError("Selecione explicitamente uma empresa chamada Homologação QA. Nenhuma alteração realizada.")
        with transaction.atomic():
            professionals=[row for row in Professional.objects.select_for_update().filter(tenant=tenant,active=True) if homologation_record(row)]
            services=[row for row in Service.objects.select_for_update().filter(tenant=tenant,active=True) if homologation_record(row)]
            appointments=[]
            for row in Appointment.objects.select_for_update().select_related("customer","service").filter(
                tenant=tenant,status__in=["pending","confirmed"],starts_at__gte=timezone.now()):
                # A real client booking a QA service is not a disposable test booking.
                if (homologation_record(row.customer) and homologation_record(row.service)
                        and "homologação" in row.notes.casefold()):
                    appointments.append(row)
            self.stdout.write(f"{tenant.name}: {len(professionals)} profissionais, {len(services)} serviços, {len(appointments)} reservas futuras.")
            if not options["apply"]:
                self.stdout.write("Simulação. Use --apply para desativar/cancelar esses registros; o histórico será preservado.")
                return
            for row in professionals+services:
                row.active=False
                row.save(update_fields=["active","updated_at"])
            for row in appointments:
                row.status=Appointment.Status.CANCELLED
                row.save(update_fields=["status","updated_at"])
                Notification.objects.filter(tenant=tenant,status="queued",payload__appointment_id=row.pk).update(status="cancelled")
            self.stdout.write(self.style.SUCCESS("Homologação encerrada. Cadastros desativados e reservas canceladas; histórico preservado."))
