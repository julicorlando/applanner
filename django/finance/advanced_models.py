"""Operational inventory and cash ledgers, separate from sales revenue."""

from core.models import TimeStampedModel
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ServiceMaterial(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="finance_material_recipes")
    service = models.ForeignKey(
        "scheduling.Service", on_delete=models.CASCADE, related_name="materials"
    )
    product = models.ForeignKey(
        "finance.Product", on_delete=models.PROTECT, related_name="service_materials"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    active = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.service_id and self.product_id and self.tenant_id:
            if (
                self.service.tenant_id != self.tenant_id
                or self.product.tenant_id != self.tenant_id
                or self.product.kind != "internal"
            ):
                raise ValidationError("Escolha serviço e insumo da mesma empresa.")
            if (
                self.product.unit_id
                and self.service.unit_id
                and self.product.unit_id != self.service.unit_id
            ):
                raise ValidationError(
                    "Serviço e insumo devem pertencer à mesma unidade."
                )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service", "product"], name="uq_service_material"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="material_qty_positive"
            ),
        ]


class MaterialConsumption(TimeStampedModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    appointment = models.ForeignKey(
        "scheduling.Appointment",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_consumptions",
    )
    product = models.ForeignKey("finance.Product", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    cost_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)
    note = models.CharField(max_length=300, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_material_consumption_key"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="consumption_qty_positive"
            ),
        ]


class CashMovement(TimeStampedModel):
    class Type(models.TextChoices):
        SUPPLY = "supply", "Suprimento"
        WITHDRAWAL = "withdrawal", "Sangria"

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    session = models.ForeignKey(
        "finance.CashSession", on_delete=models.PROTECT, related_name="movements"
    )
    type = models.CharField(max_length=12, choices=Type.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=300)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="uq_cash_movement_key"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="cash_movement_positive"
            ),
        ]
