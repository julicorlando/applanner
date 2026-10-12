from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from core.models import TimeStampedModel


class CommissionPolicy(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    professional = models.ForeignKey(
        "scheduling.Professional", on_delete=models.CASCADE
    )
    service = models.ForeignKey(
        "scheduling.Service", null=True, blank=True, on_delete=models.CASCADE
    )
    product = models.ForeignKey(
        "finance.Product", null=True, blank=True, on_delete=models.CASCADE
    )
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    deduct_materials = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    def clean(self):
        if self.service_id and self.product_id:
            raise ValidationError("Escolha serviço ou produto, não ambos.")
        for row in (
            self.professional if self.professional_id else None,
            self.service if self.service_id else None,
            self.product if self.product_id else None,
        ):
            if row and row.tenant_id != self.tenant_id:
                raise ValidationError(
                    "Todos os vínculos precisam pertencer à mesma empresa."
                )
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError("Fim da vigência anterior ao início.")
        if self.product_id and self.deduct_materials:
            raise ValidationError("Dedução de insumos aplica-se aos serviços.")

    def __str__(self):
        return self.name


class CommissionTier(models.Model):
    policy = models.ForeignKey(
        CommissionPolicy, on_delete=models.CASCADE, related_name="tiers"
    )
    threshold = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    rate = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "threshold"], name="uq_commission_tier"
            ),
            models.CheckConstraint(
                condition=models.Q(threshold__gte=0), name="tier_threshold_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0, rate__lte=100), name="tier_rate_range"
            ),
        ]
        ordering = ["threshold"]


class CommissionSnapshot(models.Model):
    commission = models.OneToOneField(
        "finance.ProfessionalCommission",
        on_delete=models.PROTECT,
        related_name="calculation",
    )
    policy = models.ForeignKey(
        CommissionPolicy, null=True, blank=True, on_delete=models.SET_NULL
    )
    details = models.JSONField(default=dict)
    earned_on = models.DateField()


class GiftCard(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    unit = models.ForeignKey(
        "tenants.Unit", null=True, blank=True, on_delete=models.PROTECT
    )
    code_hash = models.CharField(max_length=64, unique=True)
    last4 = models.CharField(max_length=4)
    issued_amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance = models.DecimalField(max_digits=12, decimal_places=2)
    expires_on = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    issue_key = models.CharField(max_length=100)
    issue_payment_method = models.CharField(max_length=40)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "issue_key"], name="uq_gift_issue"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    balance__gte=0, balance__lte=models.F("issued_amount")
                ),
                name="gift_balance_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(issued_amount__gt=0), name="gift_amount_positive"
            ),
        ]


class GiftCardEntry(models.Model):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    card = models.ForeignKey(GiftCard, on_delete=models.PROTECT, related_name="entries")
    kind = models.CharField(
        max_length=16,
        choices=[("issue", "Emissão"), ("redeem", "Uso"), ("reversal", "Estorno")],
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    command = models.ForeignKey(
        "barber.BarberCommand", null=True, blank=True, on_delete=models.PROTECT
    )
    payment = models.OneToOneField(
        "barber.BarberCommandPayment", null=True, blank=True, on_delete=models.PROTECT
    )
    reversed_entry = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uq_gift_entry_key"),
            models.CheckConstraint(
                condition=models.Q(amount__gt=Decimal("0")), name="gift_entry_positive"
            ),
        ]
