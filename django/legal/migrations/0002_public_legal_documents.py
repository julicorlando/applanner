from django.db import migrations, models
from django.utils import timezone


DOCS={
    "privacy":(
        "Política de Privacidade",
        """O ApPlanner trata dados pessoais para operar contas, agendamentos, pagamentos, comunicação, segurança e suporte. Estabelecimentos podem atuar como controladores dos dados de seus clientes e o ApPlanner pode atuar como operador, conforme o contexto. Dados podem ser compartilhados com provedores essenciais, como hospedagem, e-mail, mensageria e pagamentos, sempre de acordo com a finalidade e a legislação aplicável. O titular pode solicitar acesso, correção, informação sobre tratamento e demais direitos previstos na LGPD pelos canais oficiais da plataforma. Dados são mantidos pelo período necessário às finalidades legítimas, obrigações legais, segurança e exercício de direitos."""
    ),
    "terms_company":(
        "Termos de Uso para Empresas",
        """Ao criar uma empresa no ApPlanner, o responsável declara possuir autorização para administrar a conta e fornecer informações corretas. A empresa é responsável por seus serviços, preços, profissionais, agenda, políticas próprias, atendimento ao cliente e cumprimento das regras aplicáveis à sua atividade. O ApPlanner fornece infraestrutura de software para agenda, operação, comunicação, pagamentos e módulos contratados. Planos, módulos, limites, cobranças e períodos de teste seguem as condições apresentadas na contratação. O uso indevido, fraude, tentativa de acesso não autorizado ou violação de direitos pode resultar em restrição da conta. A empresa deve controlar permissões de seus usuários e manter seus dados atualizados."""
    ),
    "terms_customer":(
        "Termos de Uso para Clientes",
        """Ao usar páginas públicas do ApPlanner para agendar, o cliente deve informar dados verdadeiros e selecionar serviços, profissionais, horários e produtos de interesse de forma consciente. O serviço é prestado pelo estabelecimento escolhido, que responde por execução, preço, qualidade, cancelamento e condições comerciais. Produtos reservados junto ao agendamento representam interesse de compra e somente se tornam venda quando o estabelecimento registra a venda no atendimento. O ApPlanner fornece a tecnologia de intermediação e registro do fluxo."""
    ),
    "cancellation_company":(
        "Política de Cancelamento para Empresas",
        """A empresa pode cancelar sua assinatura pelos recursos disponíveis na plataforma. O cancelamento impede novas renovações após produzir efeito, sem apagar obrigações já constituídas. Valores já pagos, períodos contratados, estornos e direito de arrependimento seguem a legislação aplicável e as condições exibidas na contratação. A exclusão definitiva da conta é um processo separado e pode exigir validação pelo Master, inclusive para preservar registros legalmente necessários."""
    ),
    "cancellation_customer":(
        "Política de Cancelamento para Clientes",
        """Cancelamentos e reagendamentos de serviços seguem a política definida pelo estabelecimento e exibida ao cliente quando aplicável. O cliente deve usar os canais ou links disponibilizados para cancelar ou reagendar. Sinais, pagamentos antecipados, multas, prazos e reembolsos dependem da política informada pelo estabelecimento e da legislação aplicável. O ApPlanner registra e executa tecnicamente as regras configuradas, mas não substitui a responsabilidade do estabelecimento perante o cliente."""
    ),
}


def seed_docs(apps,schema_editor):
    LegalDocument=apps.get_model("legal","LegalDocument")
    now=timezone.now()
    for key,(title,content) in DOCS.items():
        LegalDocument.objects.get_or_create(
            type=key,version="2026-10",
            defaults={"title":title,"content":content,"status":"published","published_at":now},
        )


class Migration(migrations.Migration):
    dependencies=[("legal","0001_initial")]

    operations=[
        migrations.AlterField(
            model_name="legaldocument",
            name="type",
            field=models.CharField(
                max_length=32,
                choices=[
                    ("terms","Termos gerais"),
                    ("terms_company","Termos de uso · Empresas"),
                    ("terms_customer","Termos de uso · Clientes"),
                    ("privacy","Política de privacidade"),
                    ("cancellation_company","Política de cancelamento · Empresas"),
                    ("cancellation_customer","Política de cancelamento · Clientes"),
                ],
            ),
        ),
        migrations.RunPython(seed_docs,migrations.RunPython.noop),
    ]
