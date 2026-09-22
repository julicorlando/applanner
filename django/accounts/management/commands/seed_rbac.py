from django.core.management.base import BaseCommand

from accounts.models import Capability,PlatformRole,RoleCapability


CAPABILITIES={
    "agenda.manage":"Agenda",
    "finance.manage":"Financeiro e estoque",
    "barber.manage":"Barbearia e salão",
    "arena.manage":"Arena e quadras",
    "auto.manage":"Automotivo",
    "engagement.manage":"Relacionamento",
    "healthcare.manage":"Saúde e prontuário",
    "support.manage":"Suporte",
}
ROLES={
    "tenant-admin":("Administrador da empresa",list(CAPABILITIES)),
    "reception":("Atendimento",["agenda.manage","engagement.manage","support.manage"]),
    "finance":("Financeiro",["finance.manage"]),
    "barber-manager":("Gestor Barbearia",["agenda.manage","barber.manage","finance.manage","engagement.manage"]),
    "arena-manager":("Gestor Arena",["arena.manage","finance.manage","engagement.manage"]),
    "auto-manager":("Gestor Automotivo",["agenda.manage","auto.manage","finance.manage","engagement.manage"]),
    "healthcare":("Saúde",["agenda.manage","healthcare.manage","support.manage"]),
}


class Command(BaseCommand):
    help="Sincroniza capacidades e papéis RBAC oficiais."

    def handle(self,*args,**options):
        caps={}
        for slug,name in CAPABILITIES.items():
            caps[slug],_=Capability.objects.update_or_create(slug=slug,defaults={"name":name})
        for slug,(name,slugs) in ROLES.items():
            role,_=PlatformRole.objects.update_or_create(slug=slug,defaults={"name":name})
            RoleCapability.objects.filter(role=role).exclude(capability__slug__in=slugs).delete()
            for cap_slug in slugs:
                RoleCapability.objects.get_or_create(role=role,capability=caps[cap_slug])
        self.stdout.write(self.style.SUCCESS(f"{len(ROLES)} papéis e {len(CAPABILITIES)} capacidades sincronizados."))
