from django.core.management.base import BaseCommand

from accounts.models import Capability,PlatformRole,RoleCapability


CAPABILITIES={
    "agenda.manage":"Agenda, clientes, profissionais e serviços",
    "finance.manage":"Financeiro, estoque, PDV e comissões",
    "barber.manage":"Barbearia e salão",
    "arena.manage":"Arena e quadras",
    "auto.manage":"Automotivo",
    "engagement.manage":"Relacionamento, pacotes, fidelidade e domínio",
    "healthcare.manage":"Saúde e prontuário",
    "communications.manage":"Comunicação, notificações e WhatsApp",
    "support.manage":"Suporte",
    "commercial.manage":"Comercial",
}
ROLES={
    "tenant-admin":("Administrador da empresa",[
        "agenda.manage","finance.manage","barber.manage","arena.manage","auto.manage",
        "engagement.manage","healthcare.manage","communications.manage","support.manage",
    ]),
    "owner":("Proprietário",[
        "agenda.manage","finance.manage","barber.manage","arena.manage","auto.manage",
        "engagement.manage","healthcare.manage","communications.manage","support.manage",
    ]),
    "manager":("Gestor",[
        "agenda.manage","finance.manage","barber.manage","arena.manage","auto.manage",
        "engagement.manage","healthcare.manage","communications.manage","support.manage",
    ]),
    "reception":("Atendimento",[
        "agenda.manage","barber.manage","arena.manage","auto.manage","engagement.manage","communications.manage","support.manage",
    ]),
    "professional":("Profissional",[
        "agenda.manage","barber.manage","arena.manage","auto.manage","healthcare.manage","communications.manage","support.manage",
    ]),
    "finance":("Financeiro",["finance.manage"]),
    "barber-manager":("Gestor Barbearia",["agenda.manage","barber.manage","finance.manage","engagement.manage"]),
    "arena-manager":("Gestor Arena",["arena.manage","finance.manage","engagement.manage"]),
    "auto-manager":("Gestor Automotivo",["agenda.manage","auto.manage","finance.manage","engagement.manage"]),
    "healthcare":("Saúde",["agenda.manage","healthcare.manage","support.manage"]),
    "commercial":("Comercial",["commercial.manage","communications.manage","support.manage"]),
    "support":("Suporte",["support.manage"]),
    "user":("Usuário",["agenda.manage","communications.manage","support.manage"]),
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
        self.stdout.write(self.style.SUCCESS(
            f"{len(ROLES)} papéis e {len(CAPABILITIES)} capacidades sincronizados."
        ))
