from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("legal","0002_public_legal_documents"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.CreateModel(
            name="DataSubjectRequest",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("request_type",models.CharField(choices=[("export","Exportação de dados"),("correction","Correção de dados"),("deletion","Exclusão de dados"),("consent","Consentimento / marketing")],max_length=20)),
                ("status",models.CharField(choices=[("open","Aberta"),("in_review","Em análise"),("waiting_identity","Aguardando validação de identidade"),("completed","Concluída"),("rejected","Rejeitada"),("cancelled","Cancelada")],db_index=True,default="open",max_length=24)),
                ("requester_name",models.CharField(max_length=160)),
                ("requester_email",models.EmailField(max_length=254)),
                ("requester_phone",models.CharField(blank=True,max_length=32)),
                ("details",models.TextField(blank=True)),
                ("deadline_at",models.DateTimeField(blank=True,db_index=True,null=True)),
                ("reviewed_at",models.DateTimeField(blank=True,null=True)),
                ("completed_at",models.DateTimeField(blank=True,null=True)),
                ("resolution_notes",models.TextField(blank=True)),
                ("source",models.CharField(default="privacy_center",max_length=24)),
                ("ip_address",models.GenericIPAddressField(blank=True,null=True)),
                ("reviewed_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="data_subject_requests_reviewed",to=settings.AUTH_USER_MODEL)),
                ("tenant",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="data_subject_requests",to="tenants.tenant")),
                ("user",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="data_subject_requests",to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes":[
                    models.Index(fields=["status","deadline_at"],name="legal_dsr_status_due_idx"),
                    models.Index(fields=["requester_email","created_at"],name="legal_dsr_email_idx"),
                ],
            },
        ),
    ]
