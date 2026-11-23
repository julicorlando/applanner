"""Plano de tratamento x evolução clínica (odontologia), com ciclo de vida auditável.

- DentalPlanItem: avaliação/orçamento. Livre para editar ou apagar enquanto PLANEJADO ou EM_ORCAMENTO.
  Não aparece no histórico clínico. Ao ser executado, gera uma DentalEvolution em rascunho.
- DentalEvolution: RASCUNHO (editável/apagável pelo autor) -> FINALIZADO (imutável) -> RETIFICADO
  (original preservado, com motivo, autor e data; a correção é um novo registro ligado a ele).
- PatientNoteRectification: retificação das evoluções antigas (PatientNote, já imutáveis).

As regras valem em três camadas: serviço (evolution_services), modelo (save/delete abaixo) e
banco (triggers PostgreSQL da migration 0025). Texto clínico fica criptografado (Fernet)."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class _GuardedQuerySet(models.QuerySet):
    """Bulk writes would skip the per-row lifecycle checks, so they are refused."""

    def update(self, **kwargs):
        raise ValidationError("Use o fluxo do prontuário para alterar este registro.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use o fluxo do prontuário para alterar este registro.")

    def delete(self):
        raise ValidationError("Use o fluxo do prontuário para excluir este registro.")


class DentalPlanItem(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planejado"
        QUOTED = "quoted", "Em orçamento"
        EXECUTED = "executed", "Executado"

    EDITABLE = {Status.PLANNED, Status.QUOTED}

    objects = _GuardedQuerySet.as_manager()
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    customer = models.ForeignKey("scheduling.Customer", on_delete=models.PROTECT, related_name="dental_plan_items")
    professional = models.ForeignKey("scheduling.Professional", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="dental_plan_items")
    tooth = models.CharField(max_length=20, blank=True)
    procedure_encrypted = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    position = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLANNED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["tenant", "customer", "status"], name="dental_plan_item_patient_idx")]
        constraints = [models.CheckConstraint(
            condition=(models.Q(status="executed", executed_at__isnull=False)
                       | (~models.Q(status="executed") & models.Q(executed_at__isnull=True))),
            name="dental_plan_item_executed_state")]

    def save(self, *args, **kwargs):
        if self.pk:
            stored = type(self)._base_manager.filter(pk=self.pk).values(
                "status", "tooth", "procedure_encrypted", "price", "customer_id", "tenant_id").first()
            if stored and (stored["customer_id"] != self.customer_id or stored["tenant_id"] != self.tenant_id):
                raise ValidationError("O item do plano não muda de paciente.")
            if stored and stored["status"] == self.Status.EXECUTED and (
                    stored["tooth"] != self.tooth or stored["procedure_encrypted"] != self.procedure_encrypted
                    or stored["price"] != self.price):
                raise ValidationError("Item executado não pode ser editado; corrija pela evolução clínica.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        stored = type(self)._base_manager.filter(pk=self.pk).values_list("status", flat=True).first()
        if stored not in self.EDITABLE:
            raise ValidationError("Item executado fica registrado; corrija pela evolução clínica.")
        return super().delete(*args, **kwargs)


class DentalEvolution(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        FINALIZED = "finalized", "Finalizado"
        RECTIFIED = "rectified", "Retificado"

    # Fields that freeze at finalization (the database trigger mirrors this list).
    CLINICAL_FIELDS = ("tenant_id", "customer_id", "professional_id", "plan_item_id", "previous_id", "tooth",
                       "procedure_encrypted", "orthodontic_encrypted", "notes_encrypted", "clinical_date",
                       "author_name", "created_by_id", "created_at", "finalized_at", "finalized_by_id",
                       "finalized_automatically", "content_sha256")
    RECTIFICATION_FIELDS = ("status", "rectified_at", "rectified_by_id", "rectification_reason_encrypted", "updated_at")

    objects = _GuardedQuerySet.as_manager()
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT)
    customer = models.ForeignKey("scheduling.Customer", on_delete=models.PROTECT, related_name="dental_evolutions")
    professional = models.ForeignKey("scheduling.Professional", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="dental_evolutions")
    plan_item = models.ForeignKey(DentalPlanItem, null=True, blank=True, on_delete=models.PROTECT, related_name="evolutions")
    # referencia_registro_anterior: the record this one corrects.
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")
    tooth = models.CharField(max_length=20, blank=True)
    procedure_encrypted = models.TextField(blank=True, default="")
    orthodontic_encrypted = models.TextField(blank=True, default="")
    notes_encrypted = models.TextField(blank=True, default="")
    clinical_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    author_name = models.CharField(max_length=160)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    finalized_automatically = models.BooleanField(default=False)
    # SHA-256 of the canonical clinical content at finalization (integrity proof; the text itself stays encrypted).
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    # data_retificacao / retificado_por / motivo_retificacao
    rectified_at = models.DateTimeField(null=True, blank=True)
    rectified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    rectification_reason_encrypted = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-clinical_date", "-created_at", "-pk"]
        indexes = [models.Index(fields=["tenant", "customer", "status"], name="dental_evolution_patient_idx"),
                   models.Index(fields=["status", "created_at"], name="dental_evolution_draft_idx")]
        constraints = [models.CheckConstraint(
            condition=(models.Q(status="draft", finalized_at__isnull=True, rectified_at__isnull=True, content_sha256="")
                       | (models.Q(status="finalized", finalized_at__isnull=False, rectified_at__isnull=True)
                          & ~models.Q(content_sha256=""))
                       | (models.Q(status="rectified", finalized_at__isnull=False, rectified_at__isnull=False,
                                   rectified_by__isnull=False)
                          & ~models.Q(rectification_reason_encrypted="") & ~models.Q(content_sha256=""))),
            name="dental_evolution_lifecycle")]

    @property
    def is_draft(self):
        return self.status == self.Status.DRAFT

    def save(self, *args, **kwargs):
        if self.pk:
            stored = type(self)._base_manager.filter(pk=self.pk).values(*self.CLINICAL_FIELDS, "status").first()
            if stored and stored["status"] == self.Status.RECTIFIED:
                raise ValidationError("Registro retificado é preservado sem alterações.")
            if stored and stored["status"] == self.Status.FINALIZED:
                changed = [name for name in self.CLINICAL_FIELDS if stored[name] != getattr(self, name)]
                if changed or self.status != self.Status.RECTIFIED:
                    raise ValidationError("Registro finalizado é imutável. Use “Retificar lançamento”.")
            if stored and stored["status"] == self.Status.DRAFT and self.status == self.Status.RECTIFIED:
                raise ValidationError("Rascunho não se retifica: edite ou exclua.")
            if stored and (stored["customer_id"] != self.customer_id or stored["tenant_id"] != self.tenant_id
                           or stored["created_by_id"] != self.created_by_id):
                raise ValidationError("Vínculo clínico imutável.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        stored = type(self)._base_manager.filter(pk=self.pk).values_list("status", flat=True).first()
        if stored != self.Status.DRAFT:
            raise ValidationError("Registro finalizado não pode ser excluído. Use “Retificar lançamento”.")
        return super().delete(*args, **kwargs)


class PatientNoteRectification(models.Model):
    """Retificação de uma evolução antiga (PatientNote): a nota fica intacta e passa a ser 'retificada'."""
    objects = _GuardedQuerySet.as_manager()
    note = models.OneToOneField("healthcare.PatientNote", on_delete=models.PROTECT, related_name="rectification")
    # Empty when the note was voided (lançado por engano): nothing replaces it.
    replacement = models.OneToOneField(DentalEvolution, null=True, blank=True, on_delete=models.PROTECT, related_name="replaces_note")
    reason_encrypted = models.TextField()
    rectified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    rectified_at = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Retificação preservada sem alterações.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Retificação preservada sem alterações.")
