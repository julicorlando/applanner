from django.conf import settings
from django.db import models


class ClinicalImplementationPeriod(models.Model):
    """Janela em que a clínica transcreve prontuários anteriores ao ApPlanner."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="clinical_implementation_periods")
    starts_on = models.DateField()
    ends_on = models.DateField()
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        indexes = [models.Index(fields=["tenant", "closed_at"], name="health_impl_tenant_idx")]

    def __str__(self):
        return f"Implantação {self.starts_on:%d/%m/%Y}–{self.ends_on:%d/%m/%Y}"
