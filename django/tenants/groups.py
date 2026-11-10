from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class BusinessGroup(TimeStampedModel):
    name = models.CharField(max_length=140)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)


class GroupCompany(TimeStampedModel):
    group = models.ForeignKey(
        BusinessGroup, on_delete=models.PROTECT, related_name="companies"
    )
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    status = models.CharField(
        max_length=12,
        choices=[
            ("pending", "Convite pendente"),
            ("active", "Compartilhamento ativo"),
            ("revoked", "Revogado"),
        ],
        default="pending",
    )
    royalty_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "tenant"], name="uq_business_group_tenant"
            ),
            models.CheckConstraint(
                condition=models.Q(royalty_percent__gte=0, royalty_percent__lte=100),
                name="group_royalty_range",
            ),
        ]


class GroupRoyalty(TimeStampedModel):
    company = models.ForeignKey(
        GroupCompany, on_delete=models.PROTECT, related_name="royalties"
    )
    period = models.DateField()
    revenue_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    rate_snapshot = models.DecimalField(max_digits=5, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    expense = models.OneToOneField(
        "finance.FinancialTransaction", null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "period"], name="uq_group_royalty_period"
            )
        ]
