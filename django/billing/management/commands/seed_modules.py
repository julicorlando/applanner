from django.core.management.base import BaseCommand

from billing.models import Module


MODULES={
    "products":{
        "name":"Produtos, PDV e vendas",
        "description":"Cadastro de produtos, frente de caixa (PDV) e venda de produtos.",
        "active":True,"sort_order":10,
    },
    "stock":{
        "name":"Controle de estoque",
        "description":"Saldos, movimentações e alerta de estoque mínimo.",
        "active":True,"sort_order":20,
    },
    "finance":{
        "name":"Financeiro e controle de caixa",
        "description":"Receitas, despesas, formas de pagamento, abertura e fechamento de caixa.",
        "active":True,"sort_order":30,
    },
    "behavior":{
        "name":"Inteligência de retorno",
        "description":"Convites de retorno e relacionamento com os clientes.",
        "active":True,"sort_order":40,
    },
    "whatsapp":{"name":"WhatsApp","description":"Comunicação por WhatsApp.","active":False,"sort_order":41},
    "multiunit":{
        "name":"Multiunidade",
        "description":"Gestão de mais de uma unidade no mesmo estabelecimento.",
        "active":True,"sort_order":50,
    },
    "packages":{
        "name":"Pacotes e mensalidades",
        "description":"Pacotes de serviços, créditos e mensalidades recorrentes.",
        "active":True,"sort_order":55,
    },
    "loyalty":{
        "name":"Fidelidade",
        "description":"Pontos, regras e recompensas para fidelização.",
        "active":True,"sort_order":56,
    },
    "waitlist":{
        "name":"Lista de espera inteligente",
        "description":"Fila para preencher horários que ficarem disponíveis.",
        "active":True,"sort_order":57,
    },
    "custom_domain":{
        "name":"Domínio personalizado",
        "description":"Uso de domínio próprio na página pública.",
        "active":True,"sort_order":58,
    },
    "medical_records":{"name":"Prontuários","description":"Prontuário clínico.","active":False,"sort_order":60},
    "odontology":{"name":"Odontologia","description":"Recursos de odontologia.","active":False,"sort_order":61},
    "api":{"name":"API","description":"Acesso à API.","active":False,"sort_order":62},
    "sports_courts":{
        "name":"Arena",
        "description":"Gestão de arenas, quadras e espaços esportivos: agenda, reservas, rachas, mensalistas, comandas, CRM e operação esportiva.",
        "active":True,"sort_order":70,"addon_sellable":True,
    },
    "sports_academy":{
        "name":"Arena — Aulas e Escolinha",
        "description":"Turmas, alunos, responsáveis, presença, faltas e reposições vinculadas às quadras.",
        "active":True,"sort_order":71,"addon_sellable":True,
    },
    "sports_tournaments":{
        "name":"Arena — Torneios",
        "description":"Competições, equipes, partidas, classificação e mata-mata vinculados às quadras.",
        "active":True,"sort_order":72,"addon_sellable":True,
    },
    "banking_integrations":{
        "name":"Integrações Bancárias",
        "description":"Conexões autorizadas com provedores de pagamento, Pix, conciliação e webhooks por estabelecimento.",
        "active":True,"sort_order":80,"addon_sellable":True,
    },
}

# Slugs criados durante a replatform que não existem no catálogo tenant-facing do PHP.
DJANGO_ONLY_ALIASES={"sports","arena","barber","auto","marketing","crm","email_marketing","growth"}


class Command(BaseCommand):
    help="Cria/atualiza o catálogo base de módulos compatível com o legado."

    def handle(self,*args,**options):
        for slug,defaults in MODULES.items():
            payload={"addon_sellable":False,"sort_order":0,**defaults}
            Module.objects.update_or_create(slug=slug,defaults=payload)
        Module.objects.filter(slug__in=DJANGO_ONLY_ALIASES).update(active=False)
        self.stdout.write(self.style.SUCCESS(
            f"{len(MODULES)} módulos do catálogo legado sincronizados."
        ))
