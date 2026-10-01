from django.core.management.base import BaseCommand
from django.db import transaction

from billing.models import Module, Plan, PlanModule


SEGMENT_PLANS = (
    {"slug":"segment-barbearia-salao","name":"Barbearia / Salão","price":"29.90",
     "segment":"barbearia","modules":("finance","products","stock","packages","loyalty","waitlist"),
     "description":"Agendamentos, equipe, vendas e fidelização para barbearias e salões.",
     "features":("Agenda e página pública","Profissionais e comissões","Clientes e vendas")},
    {"slug":"segment-arena","name":"Arena","price":"49.90",
     "segment":"arena","modules":("sports_courts","finance","products","stock"),
     "description":"Quadras, horários, reservas, mensalistas e operação esportiva.",
     "features":("Reserva pública de quadras","Horários e preços","Mensalistas e financeiro")},
    {"slug":"segment-automotivo","name":"Automotivo","price":"99.90",
     "segment":"auto","modules":("finance","products","stock","packages","waitlist","behavior"),
     "description":"Veículos, agendamentos, produtos, estoque e retorno de clientes.",
     "features":("Cadastro de veículos","Agenda de serviços","Estoque, vendas e financeiro")},
    {"slug":"segment-medico","name":"Médico / Clínica","price":"0.00",
     "segment":"saude","modules":("medical_records",),
     "description":"Atendimentos clínicos e prontuários. Em preparação.",
     "features":("Agenda clínica","Prontuários e atendimento"),"active":False},
)


class Command(BaseCommand):
    help = "Cria planos por segmento sem alterar assinaturas nem ajustes do Master."

    @transaction.atomic
    def handle(self, *args, **options):
        created = 0
        for order, item in enumerate(SEGMENT_PLANS, 1):
            active=item.get("active",True)
            plan, new = Plan.objects.get_or_create(
                slug=item["slug"],
                defaults={
                    "name":item["name"],"description":item["description"],"monthly_price":item["price"],
                    "trial_days":7 if active else 0,"trial_without_card":True,
                    "active":active,"public_visible":active,
                    "featured":item["segment"]=="arena","sort_order":order,
                    "features":{"professionals":3,"units":1,"segments":[item["segment"]],
                                "included_features":list(item["features"]),
                                **({"courts":0,"reservations":0} if item["segment"]=="arena" else {})},
                },
            )
            if not new:
                if item["segment"]=="arena":
                    features=dict(plan.features or {})
                    before=dict(features)
                    features.setdefault("courts",0)
                    features.setdefault("reservations",0)
                    if features!=before:
                        plan.features=features
                        plan.save(update_fields=["features"])
                continue
            created += 1
            for module in Module.objects.filter(slug__in=item["modules"]):
                PlanModule.objects.get_or_create(plan=plan, module=module, defaults={"enabled": True})
        Plan.objects.filter(name__iexact="Arena Sports").update(public_visible=False,featured=False)
        hidden=Plan.objects.filter(slug__in=("sales-pro","sales-start","sales-business"),
                                   public_visible=True).update(public_visible=False)
        # Restore the explicitly named legacy Arena offer only when it has no
        # configuration at all. Disabled links remain a deliberate Master choice.
        arena_module=Module.objects.filter(slug="sports_courts",active=True).first()
        repaired=0
        if arena_module:
            for plan in Plan.objects.select_for_update().filter(name__iexact="Arena Sports",is_custom=False):
                if not plan.module_links.exists():
                    PlanModule.objects.create(plan=plan,module=arena_module,enabled=True)
                    if not (plan.features or {}).get("segments"):
                        plan.features={**(plan.features or {}),"segments":["arena"]}
                        plan.save(update_fields=["features"])
                    repaired+=1
        self.stdout.write(f"{repaired} planos Arena Sports sem vínculos receberam o módulo Arena.")
        self.stdout.write(self.style.SUCCESS(
            f"{created} planos por segmento criados; {hidden} planos genéricos retirados da vitrine."
        ))
