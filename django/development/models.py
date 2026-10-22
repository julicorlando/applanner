from decimal import Decimal
import uuid
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from core.models import TimeStampedModel
from core.crypto import decrypt_text


DEFAULT_MESSAGE = "Olá, {nome}! Sua cobrança de {descricao}, no valor de R$ {valor}, vence em {vencimento}. Consulte o boleto e os dados para pagamento: {link}. Se já pagou, aguarde a confirmação ou entre em contato."


class Client(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="development_client",
    )
    kind = models.CharField(
        max_length=8, choices=[("cpf", "Pessoa física"), ("cnpj", "Pessoa jurídica")]
    )
    document_encrypted = models.TextField()
    document_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField("Nome completo / razão social", max_length=180)
    company_name = models.CharField("Nome fantasia", max_length=180, blank=True)
    phone = models.CharField("WhatsApp com DDD", max_length=15)
    website = models.URLField("Link do projeto/site", blank=True, max_length=500)
    active = models.BooleanField("Cliente ativo", default=True)
    reminders_enabled = models.BooleanField(
        "Lembretes de cobrança pelo WhatsApp", default=True
    )
    message_template = models.TextField(
        "Mensagem automática de cobrança", default=DEFAULT_MESSAGE, max_length=2500
    )

    @property
    def document(self):
        return decrypt_text(self.document_encrypted)

    def __str__(self):
        return self.name


class Charge(TimeStampedModel):
    creation_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="charges")
    description = models.CharField("Descrição", max_length=200)
    amount = models.DecimalField(
        "Valor (R$)",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    due_date = models.DateField("Vencimento", db_index=True)
    status = models.CharField(
        max_length=12,
        default="open",
        choices=[("open", "Em aberto"), ("paid", "Paga"), ("cancelled", "Cancelada")],
        db_index=True,
    )
    bank = models.ForeignKey(
        "finance.PlatformBankAccount", null=True, blank=True, on_delete=models.PROTECT
    )
    boleto_url = models.URLField(
        "Link HTTPS do boleto emitido pelo banco", blank=True, max_length=1000
    )
    boleto_encrypted = models.TextField(blank=True)
    barcode = models.CharField("Linha digitável", blank=True, max_length=60)
    paid_at = models.DateTimeField(null=True, blank=True)
    settlement_note = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=1)

    @property
    def overdue(self):
        return self.status == "open" and self.due_date < timezone.localdate()


class Invitation(models.Model):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="invitations"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Delivery(TimeStampedModel):
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="deliveries"
    )
    charge = models.ForeignKey(Charge, null=True, blank=True, on_delete=models.CASCADE)
    invitation = models.ForeignKey(
        Invitation, null=True, blank=True, on_delete=models.CASCADE
    )
    channel = models.CharField(
        max_length=10, choices=[("email", "E-mail"), ("whatsapp", "WhatsApp")]
    )
    key = models.CharField(max_length=120, unique=True)
    payload_encrypted = models.TextField()
    scheduled_date = models.DateField(null=True, blank=True)
    charge_revision = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            ("pending", "Na fila"),
            ("sending", "Em envio"),
            ("sent", "Enviada"),
            ("failed", "Falhou"),
            ("uncertain", "Conferir envio"),
            ("cancelled", "Cancelada"),
        ],
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
