from django.db import migrations, models
from django.utils import timezone


def seed_documents(apps,schema_editor):
    LegalDocument=apps.get_model("legal","LegalDocument")
    now=timezone.now()
    docs=[
        ("privacy","all","1.0","Política de Privacidade do ApPlanner",
         """Esta Política explica como o ApPlanner trata dados pessoais de empresas, profissionais e clientes finais. O tratamento observa a legislação brasileira aplicável, inclusive a LGPD. Dados podem ser utilizados para cadastro, autenticação, agenda, comunicação, pagamentos, segurança, suporte, prevenção a fraudes e cumprimento de obrigações legais. Dados de clientes cadastrados por estabelecimentos são tratados conforme as finalidades definidas pelo estabelecimento e pela operação da plataforma. Dados de saúde, quando utilizados por módulos próprios, recebem tratamento restrito e controles adicionais. O titular pode exercer os direitos previstos em lei pelos canais oficiais da plataforma. Dados são mantidos pelo tempo necessário às finalidades informadas, obrigações legais, auditoria, segurança e exercício regular de direitos. Fornecedores de infraestrutura, mensageria, e-mail e pagamentos podem tratar dados estritamente para prestação dos respectivos serviços. A versão vigente desta política permanece disponível no site do ApPlanner."""),
        ("terms","company","1.0","Termos de Uso — Empresas e Profissionais",
         """Estes Termos regulam o uso do ApPlanner por estabelecimentos, profissionais e usuários internos. A empresa é responsável pelos dados cadastrados, serviços oferecidos, preços, profissionais, horários, permissões concedidas à equipe e cumprimento das normas de sua atividade. Os recursos disponíveis dependem do plano e dos módulos contratados. Assinaturas, módulos e unidades adicionais podem alterar o valor recorrente conforme as condições exibidas antes da contratação. A empresa deve manter credenciais seguras e utilizar integrações de pagamento e comunicação de forma legítima. O ApPlanner fornece infraestrutura tecnológica e não substitui o prestador do serviço oferecido ao cliente final. Cancelamento de assinatura e exclusão da conta seguem a política específica publicada na plataforma e os direitos obrigatórios previstos em lei."""),
        ("terms","customer","1.0","Termos de Uso — Clientes Finais",
         """Estes Termos regulam o uso das páginas públicas de agendamento do ApPlanner por clientes finais. O serviço agendado é prestado pelo estabelecimento escolhido, que define disponibilidade, preços, políticas comerciais e condições do atendimento. O cliente deve fornecer dados corretos e respeitar as regras de cancelamento, reagendamento, sinais e pagamentos informadas pelo estabelecimento. Reservas de produtos representam interesse para retirada no atendimento e somente se tornam venda quando confirmadas pelo estabelecimento. O ApPlanner fornece a tecnologia de agendamento e comunicação, sem substituir a responsabilidade do estabelecimento pela execução material do serviço."""),
        ("cancellation","company","1.0","Política de Cancelamento — Empresas",
         """A empresa pode solicitar o cancelamento da assinatura pela área de gestão disponível no ApPlanner. O cancelamento impede novas renovações após produzir efeitos, sem afastar valores já devidos, cobranças processadas ou obrigações legais. Módulos adicionais e unidades cobradas separadamente devem ser removidos ou cancelados conforme a configuração da assinatura. A exclusão da conta é um procedimento distinto e pode depender de análise para preservar registros exigidos por lei, segurança, auditoria ou exercício regular de direitos. Quando aplicável, direitos previstos no Código de Defesa do Consumidor e demais normas obrigatórias prevalecem."""),
        ("cancellation","customer","1.0","Política de Cancelamento — Clientes",
         """Cancelamentos e reagendamentos de serviços são definidos pelo estabelecimento responsável pelo atendimento. Antes de confirmar, o cliente deve observar prazos, regras de sinal, multas, reembolsos e condições exibidas na página pública ou informadas pelo estabelecimento. Quando o ApPlanner disponibilizar botões de cancelamento ou reagendamento, eles executarão as regras configuradas pela empresa. Em caso de cobrança online, eventual devolução seguirá a política do estabelecimento, o meio de pagamento utilizado e a legislação aplicável."""),
    ]
    for doc_type,audience,version,title,body in docs:
        LegalDocument.objects.get_or_create(
            type=doc_type,audience=audience,version=version,
            defaults={
                "title":title,"content":body,"status":"published",
                "published_at":now,
            },
        )


class Migration(migrations.Migration):
    dependencies=[("legal","0001_initial")]

    operations=[
        migrations.AddField(
            model_name="legaldocument",
            name="audience",
            field=models.CharField(
                choices=[("all","Todos"),("company","Empresas e profissionais"),("customer","Clientes finais")],
                default="all",max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="legaldocument",
            name="type",
            field=models.CharField(
                choices=[("terms","Termos de uso"),("privacy","Política de privacidade"),("cancellation","Política de cancelamento")],
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(model_name="legaldocument",name="uq_legal_type_version"),
        migrations.RemoveIndex(model_name="legaldocument",name="legal_current_idx"),
        migrations.AddConstraint(
            model_name="legaldocument",
            constraint=models.UniqueConstraint(
                fields=("type","audience","version"),
                name="uq_legal_type_audience_version",
            ),
        ),
        migrations.AddIndex(
            model_name="legaldocument",
            index=models.Index(
                fields=["type","audience","status","published_at"],
                name="legal_current_audience_idx",
            ),
        ),
        migrations.RunPython(seed_documents,migrations.RunPython.noop),
    ]
