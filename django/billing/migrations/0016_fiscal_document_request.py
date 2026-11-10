from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("billing","0015_professional_extra_quantity"),
        ("tenants","0008_tenantonboarding_email_verification_waived_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations=[
        migrations.CreateModel(
            name="FiscalDocumentRequest",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("updated_at",models.DateTimeField(auto_now=True)),
                ("reference_month",models.DateField(db_index=True)),
                ("amount",models.DecimalField(decimal_places=2,max_digits=10)),
                ("charge_breakdown",models.JSONField(blank=True,default=dict)),
                ("status",models.CharField(choices=[("requested","Solicitada"),("issued","NFe disponível"),("rejected","Não emitida")],db_index=True,default="requested",max_length=16)),
                ("requested_at",models.DateTimeField()),
                ("invoice_number",models.CharField(blank=True,max_length=80)),
                ("pdf_file",models.FileField(blank=True,upload_to="billing/nfe/pdf/%Y/%m/")),
                ("xml_file",models.FileField(blank=True,upload_to="billing/nfe/xml/%Y/%m/")),
                ("uploaded_at",models.DateTimeField(blank=True,null=True)),
                ("master_note",models.CharField(blank=True,max_length=500)),
                ("payment",models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,related_name="fiscal_document_request",to="billing.payment")),
                ("requested_by",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="fiscal_documents_requested",to=settings.AUTH_USER_MODEL)),
                ("subscription",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name="fiscal_document_requests",to="billing.subscription")),
                ("tenant",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="fiscal_document_requests",to="tenants.tenant")),
                ("uploaded_by",models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name="fiscal_documents_uploaded",to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes":[
                    models.Index(fields=["tenant","-reference_month"],name="billing_nfe_tenant_month_idx"),
                    models.Index(fields=["status","requested_at"],name="billing_nfe_status_req_idx"),
                ],
            },
        ),
    ]
