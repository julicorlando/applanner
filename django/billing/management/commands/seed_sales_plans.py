from django.core.management.base import BaseCommand
from django.db import transaction

from billing.models import Module, Plan, PlanModule


STARTER_PLANS = (
    ("sales-pro", "Profissional", "29.90", 1, ("finance",), "Agenda, clientes e financeiro para começar."),
    ("sales-start", "Inicial", "49.90", 2, ("products", "stock", "finance", "packages"), "Agenda, PDV, estoque e pacotes no mesmo lugar."),
    ("sales-business", "Empresarial", "99.90", 5, ("products", "stock", "finance", "behavior", "multiunit", "packages", "loyalty", "waitlist", "custom-domain"), "Mais unidades, fidelidade e ferramentas para crescer."),
)


class Command(BaseCommand):
    help = "Cria planos públicos de teste quando o catálogo de vendas ainda está vazio; preserva planos do legado e edições do Master."

    @transaction.atomic
    def handle(self, *args, **options):
        if Plan.objects.filter(active=True, public_visible=True, is_custom=False).exists():
            self.stdout.write("Catálogo público já configurado; nenhum plano alterado.")
            return
        created = 0
        for order, (slug, name, price, professionals, modules, description) in enumerate(STARTER_PLANS, 1):
            plan, new = Plan.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name, "description": description, "monthly_price": price,
                    "trial_days": 7, "trial_without_card": True,
                    "active": True, "public_visible": True, "featured": order == 2,
                    "sort_order": order,
                    "features": {"professionals": professionals, "units": 1,
                                 "segments": ["barbearia","auto","arena","saude"],
                                 "included_features": ["Agenda online e gestão de clientes"]},
                },
            )
            if not new:
                continue
            created += 1
            for module in Module.objects.filter(slug__in=modules, active=True):
                PlanModule.objects.get_or_create(plan=plan, module=module, defaults={"enabled": True})
        self.stdout.write(self.style.SUCCESS(f"{created} planos públicos criados para homologação."))
