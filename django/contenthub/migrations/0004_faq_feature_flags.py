from django.db import migrations, models


def seed_public_content(apps,schema_editor):
    FAQItem=apps.get_model("contenthub","FAQItem")
    PlatformFeatureFlag=apps.get_model("contenthub","PlatformFeatureFlag")
    PlatformFeatureFlag.objects.get_or_create(
        key="healthcare_public",
        defaults={
            "label":"Exibir Médico / Clínica no site público",
            "description":"Controla a exibição pública de planos e do segmento de clínicas.",
            "enabled":False,
        },
    )
    defaults=[
        ("Como funciona o teste grátis?","O período de teste e a necessidade de cartão dependem do plano escolhido. As condições aparecem antes da criação da conta.",10),
        ("Posso cancelar minha assinatura?","Sim. O responsável da empresa pode solicitar o cancelamento pela área Meu plano e pagamento, observadas as condições contratadas e a legislação aplicável.",20),
        ("Como meus clientes agendam?","Cada empresa recebe uma página pública. O cliente escolhe serviço, profissional, data e horário conforme a disponibilidade configurada.",30),
        ("O ApPlanner permite vários profissionais?","Sim. A quantidade disponível depende do plano contratado e de eventuais liberações do Master.",40),
        ("Posso vender produtos junto com o atendimento?","Quando o módulo de produtos estiver disponível, a empresa pode cadastrar estoque e registrar vendas. O cliente também pode demonstrar interesse em produtos ao agendar.",50),
        ("Como funciona a lista de espera?","Quando habilitada no plano, clientes podem entrar na lista de espera e a equipe pode organizar o retorno quando surgir disponibilidade.",60),
    ]
    for question,answer,sort_order in defaults:
        FAQItem.objects.get_or_create(
            question=question,
            defaults={"answer":answer,"sort_order":sort_order,"active":True},
        )


class Migration(migrations.Migration):
    dependencies=[("contenthub","0003_platformhomepage")]

    operations=[
        migrations.CreateModel(
            name="FAQItem",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("question",models.CharField(max_length=220)),
                ("answer",models.TextField()),
                ("category",models.CharField(blank=True,max_length=80)),
                ("sort_order",models.PositiveSmallIntegerField(default=0)),
                ("active",models.BooleanField(default=True)),
            ],
            options={"ordering":["sort_order","question"]},
        ),
        migrations.CreateModel(
            name="PlatformFeatureFlag",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("key",models.SlugField(max_length=80,unique=True)),
                ("label",models.CharField(max_length=160)),
                ("description",models.CharField(blank=True,max_length=500)),
                ("enabled",models.BooleanField(default=False)),
            ],
            options={"ordering":["label"]},
        ),
        migrations.RunPython(seed_public_content,migrations.RunPython.noop),
    ]
