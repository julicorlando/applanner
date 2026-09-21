from django.core.management.base import BaseCommand

from billing.models import Module


MODULES={
    "products":"Produtos",
    "stock":"Estoque",
    "finance":"Financeiro",
    "behavior":"Behavior Engine",
    "whatsapp":"WhatsApp",
    "multiunit":"Multiunidade",
    "medical_records":"Prontuário",
    "odontology":"Odontologia",
    "api":"API",
    "sports":"Quadras e esportes",
    "arena":"ApPlanner Arena",
    "barber":"ApPlanner Barber",
    "auto":"ApPlanner Auto",
    "packages":"Pacotes e mensalidades",
    "loyalty":"Fidelidade",
    "waitlist":"Lista de espera inteligente",
    "custom_domain":"Domínio personalizado",
    "marketing":"Marketing",
    "crm":"CRM",
    "email_marketing":"E-mail marketing",
    "growth":"Growth e funil",
}


class Command(BaseCommand):
    help="Cria/atualiza o catálogo oficial de módulos do ApPlanner."

    def handle(self,*args,**options):
        for slug,name in MODULES.items():
            Module.objects.update_or_create(slug=slug,defaults={"name":name,"active":True})
        self.stdout.write(self.style.SUCCESS(f"{len(MODULES)} módulos sincronizados."))
