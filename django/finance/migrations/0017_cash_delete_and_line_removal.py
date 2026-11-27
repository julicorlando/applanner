import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Aditiva: exclusão de caixa pelo gestor e pedidos de apagar lançamento."""

    dependencies = [
        ("finance", "0016_cash_session_professional_day"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="cashsession", name="deleted_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="cashsession", name="deleted_by", field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cash_sessions_deleted", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="cashsession", name="deleted_reason", field=models.CharField(blank=True, max_length=300)),
        migrations.CreateModel(
            name="ClinicCashEntryRemoval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=300)),
                ("status", models.CharField(choices=[("requested", "Aguardando gestor"), ("approved", "Apagado"), ("rejected", "Recusado")], db_index=True, default="requested", max_length=12)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("entry", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="removal_requests", to="finance.cliniccashentry")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.AddConstraint(model_name="cliniccashentryremoval", constraint=models.UniqueConstraint(
            condition=models.Q(("status", "requested")), fields=("entry",), name="uq_clinic_cash_removal_pending")),
    ]
