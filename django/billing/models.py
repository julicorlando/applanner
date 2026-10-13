from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator,MaxValueValidator
from decimal import Decimal
from django.utils import timezone
from core.models import TimeStampedModel


class Module(models.Model):
    slug=models.SlugField(max_length=80,unique=True)
    name=models.CharField(max_length=120)
    description=models.CharField(max_length=500,blank=True)
    addon_monthly_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    addon_sellable=models.BooleanField(default=False)
    per_unit_billing=models.BooleanField(default=False)
    sort_order=models.SmallIntegerField(default=0)
    active=models.BooleanField(default=True)

    def save(self,*args,**kwargs):
        if self.pk:
            previous=type(self).objects.filter(pk=self.pk).first()
            if previous and previous.per_unit_billing and previous.addon_monthly_price is not None and previous.addon_monthly_price!=self.addon_monthly_price:
                for addon in self.addons.filter(status="active",pricing_components=[]):
                    addon.pricing_components=[str(previous.addon_monthly_price)]
                    addon.save(update_fields=["pricing_components","updated_at"])
        return super().save(*args,**kwargs)

    def __str__(self):
        return self.name


class Plan(TimeStampedModel):
    name=models.CharField(max_length=100)
    slug=models.SlugField(max_length=80,unique=True)
    description=models.CharField(max_length=500,blank=True)
    monthly_price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    quarterly_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    semiannual_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    annual_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    quarterly_discount=models.DecimalField("Desconto trimestral (%)",max_digits=5,decimal_places=2,default=0,blank=True,validators=[MinValueValidator(0),MaxValueValidator(Decimal("99.99"))])
    semiannual_discount=models.DecimalField("Desconto semestral (%)",max_digits=5,decimal_places=2,default=0,blank=True,validators=[MinValueValidator(0),MaxValueValidator(Decimal("99.99"))])
    annual_discount=models.DecimalField("Desconto anual (%)",max_digits=5,decimal_places=2,default=0,blank=True,validators=[MinValueValidator(0),MaxValueValidator(Decimal("99.99"))])
    promotion_price=models.DecimalField("Preço mensal promocional",max_digits=10,decimal_places=2,null=True,blank=True,validators=[MinValueValidator(Decimal("0.01"))])
    promotion_months=models.PositiveSmallIntegerField("Meses da promoção após o teste",default=0,blank=True)
    promotion_starts_at=models.DateTimeField("Início da oferta",null=True,blank=True)
    promotion_ends_at=models.DateTimeField("Fim da oferta para novas contratações",null=True,blank=True)
    trial_days=models.PositiveSmallIntegerField(default=14)
    trial_without_card=models.BooleanField(default=True)
    active=models.BooleanField(default=True)
    public_visible=models.BooleanField(default=True)
    is_custom=models.BooleanField(default=False)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="created_plans")
    featured=models.BooleanField(default=False)
    sort_order=models.SmallIntegerField(default=0)
    features=models.JSONField(default=dict,blank=True)
    modules=models.ManyToManyField(Module,through="PlanModule",related_name="plans",blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        errors={}
        for cycle in ('monthly','quarterly','semiannual','annual'):
            value=getattr(self,cycle+'_price')
            if value is not None and value<0: errors[cycle+'_price']='O preço não pode ser negativo.'
        for cycle in ('quarterly','semiannual','annual'):
            if getattr(self,cycle+'_discount',0) and getattr(self,cycle+'_price') is not None:
                errors[cycle+'_discount']='Deixe o preço fixo deste ciclo vazio para usar o desconto percentual.'
        if self.promotion_price is not None:
            if not self.promotion_months: errors['promotion_months']='Informe quantos meses a promoção dura.'
            if self.promotion_price>=self.monthly_price: errors['promotion_price']='O preço promocional deve ser menor que o preço mensal regular.'
        elif self.promotion_months: errors['promotion_price']='Informe o preço promocional.'
        if self.promotion_starts_at and self.promotion_ends_at and self.promotion_ends_at<=self.promotion_starts_at:
            errors['promotion_ends_at']='O fim da oferta deve ser posterior ao início.'
        if errors: raise ValidationError(errors)

    def save(self,*args,**kwargs):
        if self.pk:
            previous=type(self).objects.filter(pk=self.pk).first()
            if previous and any(getattr(previous,key)!=getattr(self,key) for key in ('monthly_price','quarterly_price','semiannual_price','annual_price','quarterly_discount','semiannual_discount','annual_discount')):
                from .commercial_pricing import freeze_plan_contracts
                freeze_plan_contracts(previous)
        return super().save(*args,**kwargs)

    def __str__(self):
        return self.name


class PlanModule(models.Model):
    plan=models.ForeignKey(Plan,on_delete=models.CASCADE,related_name="module_links")
    module=models.ForeignKey(Module,on_delete=models.CASCADE,related_name="plan_links")
    enabled=models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["plan","module"],name="uq_plan_module")]


class TenantModule(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="module_links")
    module=models.ForeignKey(Module,on_delete=models.CASCADE,related_name="tenant_links")
    enabled=models.BooleanField(default=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","module"],name="uq_tenant_module")]


class Subscription(TimeStampedModel):
    class PaymentMethod(models.TextChoices):
        CARD="card","Cartão · assinatura automática"
        PIX="pix","Pix · pagamento por ciclo"

    class Status(models.TextChoices):
        TRIAL="trial","Teste"
        ACTIVE="active","Ativa"
        PAST_DUE="past_due","Em atraso"
        SUSPENDED="suspended","Suspensa"
        CANCELLED="cancelled","Cancelada"

    class BillingCycle(models.TextChoices):
        MONTHLY="monthly","Mensal"
        QUARTERLY="quarterly","Trimestral"
        SEMIANNUAL="semiannual","Semestral"
        ANNUAL="annual","Anual"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="subscriptions")
    plan=models.ForeignKey(Plan,on_delete=models.PROTECT)
    billing_cycle=models.CharField(max_length=16,choices=BillingCycle.choices,default=BillingCycle.MONTHLY)
    contracted_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    base_contracted_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    addon_contracted_price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    regular_base_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    promotion_ends_at=models.DateTimeField(null=True,blank=True)
    commercial_snapshot=models.JSONField(default=dict,blank=True)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.TRIAL,db_index=True)
    started_at=models.DateTimeField()
    trial_started_at=models.DateTimeField(null=True,blank=True)
    trial_ends_at=models.DateTimeField(null=True,blank=True)
    trial_days_snapshot=models.PositiveSmallIntegerField(null=True,blank=True)
    next_billing_at=models.DateTimeField(null=True,blank=True,db_index=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)
    provider_customer_id=models.CharField(max_length=190,blank=True)
    provider_subscription_id=models.CharField(max_length=190,blank=True,db_index=True)
    provider_environment=models.CharField(max_length=16,blank=True)
    provider_plan_id=models.CharField(max_length=190,blank=True)
    provider_checkout_url=models.URLField(max_length=1000,blank=True)
    payment_method=models.CharField(max_length=8,choices=PaymentMethod.choices,blank=True,default="")
    payment_method_version=models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.plan.name} · {self.tenant.name}" if self.plan_id and self.tenant_id else "Nova assinatura"


class CheckoutSession(TimeStampedModel):
    class Status(models.TextChoices):
        STARTED="started","Iniciado"
        AWAITING_PAYMENT="awaiting_payment","Aguardando pagamento"
        PAID="paid","Pago"
        EXPIRED="expired","Expirado"
        ABANDONED="abandoned","Abandonado"
        FAILED="failed","Falhou"

    public_id=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="checkout_sessions")
    plan=models.ForeignKey(Plan,on_delete=models.PROTECT)
    billing_cycle=models.CharField(max_length=16,choices=Subscription.BillingCycle.choices)
    subtotal=models.DecimalField(max_digits=10,decimal_places=2)
    discount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    total=models.DecimalField(max_digits=10,decimal_places=2)
    base_total=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    addon_total=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    coupon_code=models.CharField(max_length=60,blank=True)
    status=models.CharField(max_length=24,choices=Status.choices,default=Status.STARTED,db_index=True)
    idempotency_key=models.CharField(max_length=64,unique=True)
    expires_at=models.DateTimeField(db_index=True)


class Coupon(TimeStampedModel):
    class Type(models.TextChoices):
        PERCENT="percent","Percentual"
        FIXED="fixed","Valor fixo"

    code=models.CharField(max_length=60,unique=True)
    type=models.CharField(max_length=12,choices=Type.choices)
    value=models.DecimalField(max_digits=10,decimal_places=2)
    valid_from=models.DateTimeField(null=True,blank=True)
    valid_until=models.DateTimeField(null=True,blank=True)
    max_uses=models.PositiveIntegerField(null=True,blank=True)
    uses_count=models.PositiveIntegerField(default=0)
    active=models.BooleanField(default=True)


class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        OVERDUE="overdue","Vencida"
        CANCELLED="cancelled","Cancelada"
        REFUNDED="refunded","Estornada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="invoices")
    subscription=models.ForeignKey(Subscription,on_delete=models.PROTECT,related_name="invoices")
    checkout_session=models.ForeignKey(CheckoutSession,null=True,blank=True,on_delete=models.SET_NULL,related_name="invoices")
    number=models.CharField(max_length=60,unique=True)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    currency=models.CharField(max_length=3,default="BRL")
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    due_at=models.DateTimeField(db_index=True)
    paid_at=models.DateTimeField(null=True,blank=True)


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        FAILED="failed","Falhou"
        EXPIRED="expired","Expirado"
        REFUNDED="refunded","Estornado"
        PARTIALLY_REFUNDED="partially_refunded","Estorno parcial"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="payments")
    subscription=models.ForeignKey(Subscription,null=True,blank=True,on_delete=models.SET_NULL,related_name="payments")
    purpose=models.CharField(max_length=40,default="subscription")
    reference_id=models.BigIntegerField(null=True,blank=True)
    provider=models.CharField(max_length=60,blank=True)
    environment=models.CharField(max_length=20,default="unknown")
    provider_reference=models.CharField(max_length=190,blank=True,db_index=True)
    provider_status=models.CharField(max_length=80,blank=True)
    provider_payment_id=models.CharField(max_length=190,blank=True)
    idempotency_key=models.CharField(max_length=100,blank=True)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.PENDING,db_index=True)
    due_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    metadata=models.JSONField(default=dict,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["provider","provider_payment_id"],
                condition=~models.Q(provider_payment_id=""),
                name="uq_payment_provider_id",
            ),
            models.UniqueConstraint(
                fields=["tenant","idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uq_payment_idempotency",
            ),
        ]
        indexes=[models.Index(fields=["purpose","reference_id","status"])]


class FiscalDocumentRequest(TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED="requested","Solicitada"
        ISSUED="issued","NFe disponível"
        REJECTED="rejected","Não emitida"

    tenant=models.ForeignKey(
        "tenants.Tenant",on_delete=models.CASCADE,related_name="fiscal_document_requests"
    )
    subscription=models.ForeignKey(
        Subscription,on_delete=models.PROTECT,related_name="fiscal_document_requests"
    )
    payment=models.OneToOneField(
        Payment,on_delete=models.PROTECT,related_name="fiscal_document_request"
    )
    reference_month=models.DateField(db_index=True)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    charge_breakdown=models.JSONField(default=dict,blank=True)
    status=models.CharField(
        max_length=16,choices=Status.choices,default=Status.REQUESTED,db_index=True
    )
    requested_by=models.ForeignKey(
        settings.AUTH_USER_MODEL,on_delete=models.PROTECT,
        related_name="fiscal_documents_requested",
    )
    requested_at=models.DateTimeField()
    invoice_number=models.CharField(max_length=80,blank=True)
    pdf_file=models.FileField(upload_to="billing/nfe/pdf/%Y/%m/",blank=True)
    xml_file=models.FileField(upload_to="billing/nfe/xml/%Y/%m/",blank=True)
    uploaded_by=models.ForeignKey(
        settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,
        related_name="fiscal_documents_uploaded",
    )
    uploaded_at=models.DateTimeField(null=True,blank=True)
    master_note=models.CharField(max_length=500,blank=True)
    emission_state=models.CharField(max_length=20,default="manual",choices=[("manual","Manual"),("queued","Na fila"),("processing","Em processamento"),("waiting","Aguardando consulta"),("error","Precisa de atenção"),("authorized","Autorizada")],db_index=True)
    fiscal_environment=models.CharField(max_length=16,blank=True)
    issuer_document=models.CharField(max_length=14,blank=True)
    dps_id=models.CharField(max_length=50,blank=True)
    signed_dps_encrypted=models.TextField(blank=True)
    access_key=models.CharField(max_length=50,blank=True)
    attempts=models.PositiveIntegerField(default=0)
    next_attempt_at=models.DateTimeField(null=True,blank=True)
    processing_until=models.DateTimeField(null=True,blank=True)
    last_error=models.CharField(max_length=500,blank=True)
    emission_history=models.JSONField(default=list,blank=True)
    notice_queued_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","-reference_month"],name="billing_nfe_tenant_month_idx"),
            models.Index(fields=["status","requested_at"],name="billing_nfe_status_req_idx"),
        ]


class PlatformFiscalSettings(TimeStampedModel):
    """Single MEI issuer. Private key and password never enter file storage or audit."""
    enabled=models.BooleanField("Emitir automaticamente após pagamento",default=False)
    auto_from=models.DateTimeField("Pagamentos a partir de",default=timezone.now)
    environment=models.CharField("Ambiente",max_length=16,choices=[("homologation","Homologação — sem validade fiscal"),("production","Produção")],default="homologation")
    document=models.CharField("CNPJ do MEI",max_length=14)
    legal_name=models.CharField("Razão social",max_length=150)
    municipality_code=models.CharField("Código IBGE do município emissor",max_length=7)
    service_code=models.CharField("Código nacional de tributação do serviço",max_length=6)
    municipal_service_code=models.CharField("Código municipal do serviço (opcional)",max_length=3,blank=True)
    service_description=models.CharField("Descrição do serviço",max_length=1000)
    series=models.PositiveIntegerField("Série exclusiva da DPS nesta aplicação",default=1,validators=[MinValueValidator(1),MaxValueValidator(49999)])
    certificate_encrypted=models.TextField(blank=True)
    certificate_password_encrypted=models.TextField(blank=True)
    certificate_expires_at=models.DateTimeField(null=True,blank=True)
    tax_confirmed=models.BooleanField("Confirmei com a contabilidade o enquadramento MEI, código e competência do serviço",default=False)

    def save(self,*args,**kwargs):
        self.pk=1
        return super().save(*args,**kwargs)


class TenantFiscalProfile(TimeStampedModel):
    tenant=models.OneToOneField("tenants.Tenant",on_delete=models.CASCADE,related_name="fiscal_profile")
    document=models.CharField("CPF/CNPJ",max_length=14)
    legal_name=models.CharField("Nome / razão social",max_length=150)
    email=models.EmailField("E-mail fiscal",max_length=80)
    municipality_code=models.CharField("Código IBGE do município",max_length=7)
    postal_code=models.CharField("CEP",max_length=8)
    street=models.CharField("Logradouro",max_length=255)
    number=models.CharField("Número",max_length=60)
    district=models.CharField("Bairro",max_length=60)
    complement=models.CharField("Complemento",max_length=156,blank=True)


class SubscriptionHistory(models.Model):
    subscription=models.ForeignKey(Subscription,on_delete=models.CASCADE,related_name="history")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="subscription_history")
    from_plan=models.ForeignKey(Plan,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    to_plan=models.ForeignKey(Plan,null=True,blank=True,on_delete=models.SET_NULL,related_name="+")
    from_status=models.CharField(max_length=30,blank=True)
    to_status=models.CharField(max_length=30,blank=True)
    reason=models.CharField(max_length=120,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)


class ModuleRequest(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        APPROVED="approved","Aprovado"
        AWAITING_PAYMENT="awaiting_payment","Aguardando pagamento"
        ACTIVE="active","Ativo"
        PAYMENT_FAILED="payment_failed","Falha no pagamento"
        REJECTED="rejected","Rejeitado"
        CANCELLED="cancelled","Cancelado"

    public_id=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="module_requests")
    module=models.ForeignKey(Module,on_delete=models.PROTECT,related_name="requests")
    requested_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="module_requests")
    quoted_monthly_price=models.DecimalField(max_digits=10,decimal_places=2)
    status=models.CharField(max_length=24,choices=Status.choices,default=Status.PENDING,db_index=True)
    tenant_note=models.CharField(max_length=500,blank=True)
    master_note=models.CharField(max_length=500,blank=True)
    reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="reviewed_module_requests")
    reviewed_at=models.DateTimeField(null=True,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True)


class TenantModuleAddon(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        ACTIVE="active","Ativo"
        PAST_DUE="past_due","Em atraso"
        CANCELLED="cancelled","Cancelado"

    class BillingMode(models.TextChoices):
        SEPARATE="separate","Separada"
        MERGED="merged_subscription","Incorporada à assinatura"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="module_addons")
    module=models.ForeignKey(Module,on_delete=models.PROTECT,related_name="addons")
    module_request=models.ForeignKey(ModuleRequest,null=True,blank=True,on_delete=models.SET_NULL,related_name="addons")
    monthly_price=models.DecimalField(max_digits=10,decimal_places=2)
    quantity=models.PositiveIntegerField(default=1)
    pricing_components=models.JSONField(default=list,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    billing_mode=models.CharField(max_length=24,choices=BillingMode.choices,default=BillingMode.SEPARATE)
    provider=models.CharField(max_length=40,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    next_billing_at=models.DateTimeField(null=True,blank=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","module"],name="uq_tenant_module_addon")]


class PaymentGateway(TimeStampedModel):
    class Environment(models.TextChoices):
        SANDBOX="sandbox","Sandbox"
        PRODUCTION="production","Produção"

    class TestStatus(models.TextChoices):
        NOT_VALIDATED="not_validated","Não validado"
        VALIDATED="validated","Validado"
        FAILED="failed","Falhou"

    provider=models.CharField(max_length=60,default="mercadopago")
    environment=models.CharField(max_length=16,choices=Environment.choices)
    public_key=models.CharField(max_length=190,blank=True)
    access_token_encrypted=models.TextField()
    webhook_secret_encrypted=models.TextField()
    webhook_url=models.URLField(max_length=500)
    active=models.BooleanField(default=False)
    last_tested_at=models.DateTimeField(null=True,blank=True)
    last_test_status=models.CharField(max_length=20,choices=TestStatus.choices,default=TestStatus.NOT_VALIDATED)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["provider","environment"],name="uq_payment_gateway_env"),
        ]


class WebhookEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED="received","Recebido"
        PROCESSED="processed","Processado"
        REJECTED="rejected","Rejeitado"
        FAILED="failed","Falhou"

    provider=models.CharField(max_length=60)
    event_id=models.CharField(max_length=190)
    resource_type=models.CharField(max_length=60,blank=True)
    resource_id=models.CharField(max_length=190,blank=True)
    signature_valid=models.BooleanField(default=False)
    payload_hash=models.CharField(max_length=64)
    payload=models.JSONField(default=dict,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.RECEIVED,db_index=True)
    error_message=models.CharField(max_length=500,blank=True)
    received_at=models.DateTimeField(auto_now_add=True)
    processed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["provider","event_id"],name="uq_webhook_event")]
        indexes=[models.Index(fields=["provider","status","received_at"],name="billing_webhook_status_idx")]


class TenantPaymentConnection(TimeStampedModel):
    class AuthType(models.TextChoices):
        OAUTH="oauth","OAuth"
        API_CREDENTIALS="api_credentials","Credenciais de API"
        MANUAL="manual","Manual"

    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        CONNECTED="connected","Conectado"
        ERROR="error","Erro"
        DISABLED="disabled","Desabilitado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="payment_connections")
    provider=models.CharField(max_length=60,default="mercadopago")
    display_name=models.CharField(max_length=120,default="Mercado Pago")
    environment=models.CharField(max_length=16,choices=PaymentGateway.Environment.choices)
    auth_type=models.CharField(max_length=20,choices=AuthType.choices,default=AuthType.API_CREDENTIALS)
    credentials_encrypted=models.TextField(blank=True)
    metadata=models.JSONField(default=dict,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    last_tested_at=models.DateTimeField(null=True,blank=True)
    last_sync_at=models.DateTimeField(null=True,blank=True)
    last_error_code=models.CharField(max_length=120,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="payment_connections_created")

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["tenant","provider","environment"],name="uq_tenant_payment_connection"),
        ]


class TenantBankAccount(TimeStampedModel):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="bank_accounts")
    bank_code=models.CharField(max_length=12,blank=True)
    bank_name=models.CharField(max_length=120)
    holder_name=models.CharField(max_length=160)
    details_encrypted=models.TextField()
    account_last4=models.CharField(max_length=4,blank=True)
    pix_key_last4=models.CharField(max_length=4,blank=True)
    is_primary=models.BooleanField(default=False)
    active=models.BooleanField(default=True)
    created_by=models.ForeignKey(
        settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,
        related_name="tenant_bank_accounts_created",
    )

    class Meta:
        indexes=[models.Index(fields=["tenant","active"],name="billing_bank_tenant_idx")]
        constraints=[
            models.UniqueConstraint(
                fields=["tenant"],condition=models.Q(is_primary=True,active=True),
                name="uq_primary_bank_account_tenant",
            ),
        ]

    def __str__(self):
        suffix=f" •••• {self.account_last4}" if self.account_last4 else ""
        return f"{self.bank_name}{suffix}"


class TenantPaymentTransaction(TimeStampedModel):
    class Status(models.TextChoices):
        CREATED="created","Criado"
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        FAILED="failed","Falhou"
        CANCELLED="cancelled","Cancelado"
        EXPIRED="expired","Expirado"
        REFUNDED="refunded","Estornado"
        PARTIALLY_REFUNDED="partially_refunded","Estorno parcial"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="payment_transactions")
    connection=models.ForeignKey(TenantPaymentConnection,on_delete=models.PROTECT,related_name="transactions")
    reference_type=models.CharField(max_length=40)
    reference_id=models.BigIntegerField()
    external_reference=models.CharField(max_length=190)
    provider_transaction_id=models.CharField(max_length=190,blank=True)
    method=models.CharField(max_length=40)
    gross_amount=models.DecimalField(max_digits=12,decimal_places=2)
    fee_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    net_amount=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.CREATED,db_index=True)
    expires_at=models.DateTimeField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    reconciled_at=models.DateTimeField(null=True,blank=True)
    idempotency_key=models.CharField(max_length=100)
    pix_qr_code=models.TextField(blank=True)
    pix_copy_paste=models.TextField(blank=True)
    checkout_url=models.URLField(max_length=1000,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["tenant","idempotency_key"],name="uq_tenant_payment_tx_idempotency"),
            models.UniqueConstraint(fields=["connection","external_reference"],name="uq_tenant_payment_external"),
        ]
        indexes=[
            models.Index(fields=["tenant","reference_type","reference_id"],name="billing_tpt_ref_idx"),
            models.Index(fields=["provider_transaction_id"],name="billing_tpt_provider_idx"),
        ]


class TenantRecurringSubscription(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        AUTHORIZED="authorized","Autorizada"
        PAUSED="paused","Pausada"
        CANCELLED="cancelled","Cancelada"
        ERROR="error","Erro"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="recurring_subscriptions")
    connection=models.ForeignKey(TenantPaymentConnection,on_delete=models.PROTECT,related_name="recurring_subscriptions")
    reference_type=models.CharField(max_length=40)
    reference_id=models.BigIntegerField()
    external_reference=models.CharField(max_length=190)
    provider_subscription_id=models.CharField(max_length=190,blank=True)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    cycle_months=models.PositiveSmallIntegerField(default=1)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    checkout_url=models.URLField(max_length=1000,blank=True)
    idempotency_key=models.CharField(max_length=100)
    last_payment_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["tenant","idempotency_key"],name="uq_tenant_recurring_idempotency"),
            models.UniqueConstraint(
                fields=["connection","provider_subscription_id"],
                condition=~models.Q(provider_subscription_id=""),
                name="uq_tenant_recurring_provider",
            ),
        ]
        indexes=[models.Index(fields=["tenant","reference_type","reference_id"],name="billing_trs_ref_idx")]


class TenantPaymentWebhookEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED="received","Recebido"
        PROCESSED="processed","Processado"
        IGNORED="ignored","Ignorado"
        FAILED="failed","Falhou"

    connection=models.ForeignKey(TenantPaymentConnection,on_delete=models.CASCADE,related_name="webhook_events")
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="payment_webhook_events")
    provider=models.CharField(max_length=40)
    event_id=models.CharField(max_length=190)
    payload_hash=models.CharField(max_length=64)
    signature_valid=models.BooleanField(default=False)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.RECEIVED,db_index=True)
    error_code=models.CharField(max_length=80,blank=True)
    received_at=models.DateTimeField(auto_now_add=True)
    processed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=["connection","event_id"],name="uq_tenant_webhook_event"),
        ]
        indexes=[models.Index(fields=["tenant","received_at"],name="billing_tenant_webhook_idx")]


class SubscriptionExemption(TimeStampedModel):
    class Type(models.TextChoices):
        TEMPORARY="temporary","Temporária"
        PERMANENT="permanent","Permanente"
    class Status(models.TextChoices):
        ACTIVE="active","Ativa"
        REVOKED="revoked","Revogada"
        EXPIRED="expired","Expirada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="subscription_exemptions")
    subscription=models.ForeignKey(Subscription,null=True,blank=True,on_delete=models.SET_NULL,related_name="exemptions")
    exemption_type=models.CharField(max_length=12,choices=Type.choices,default=Type.TEMPORARY)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField(null=True,blank=True)
    reason=models.CharField(max_length=500)
    status=models.CharField(max_length=12,choices=Status.choices,default=Status.ACTIVE,db_index=True)
    granted_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="subscription_exemptions_granted")
    revoked_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="subscription_exemptions_revoked")
    revoked_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","starts_at","ends_at"],name="billing_exempt_tenant_idx")]


class SubscriptionModuleAdjustment(TimeStampedModel):
    class Action(models.TextChoices):
        ADD="add","Adicionar"
        REMOVE="remove","Remover"
        CONSOLIDATE="consolidate","Consolidar"
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        APPLIED="applied","Aplicado"
        FAILED="failed","Falhou"
        SYNC_REQUIRED="sync_required","Sincronização necessária"

    public_id=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="subscription_module_adjustments")
    subscription=models.ForeignKey(Subscription,on_delete=models.CASCADE,related_name="module_adjustments")
    module_request=models.ForeignKey(ModuleRequest,null=True,blank=True,on_delete=models.SET_NULL,related_name="adjustments")
    module_addon=models.ForeignKey(TenantModuleAddon,null=True,blank=True,on_delete=models.SET_NULL,related_name="adjustments")
    action=models.CharField(max_length=16,choices=Action.choices)
    previous_amount=models.DecimalField(max_digits=10,decimal_places=2)
    new_amount=models.DecimalField(max_digits=10,decimal_places=2)
    addon_monthly_price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    provider=models.CharField(max_length=40,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True)
    idempotency_key=models.CharField(max_length=64,unique=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    error_code=models.CharField(max_length=120,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="subscription_module_adjustments_created")
    applied_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[
            models.Index(fields=["tenant","status","created_at"],name="billing_modadj_tenant_idx"),
            models.Index(fields=["subscription","created_at"],name="billing_modadj_sub_idx"),
        ]


class SubscriptionNoticeLog(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="subscription_notices")
    subscription=models.ForeignKey(Subscription,on_delete=models.CASCADE,related_name="notice_logs")
    notice_key=models.CharField(max_length=40)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["subscription","notice_key"],name="uq_subscription_notice")]
        indexes=[models.Index(fields=["tenant","created_at"],name="billing_notice_tenant_idx")]


class ProviderEvent(models.Model):
    provider=models.CharField(max_length=40)
    event_id=models.CharField(max_length=190)
    event_type=models.CharField(max_length=100,blank=True)
    payload_hash=models.CharField(max_length=64)
    status=models.CharField(max_length=16,default="received",db_index=True)
    error_message=models.CharField(max_length=500,blank=True)
    received_at=models.DateTimeField()
    processed_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["provider","event_id"],name="uq_provider_event")]
        indexes=[models.Index(fields=["provider","status","received_at"],name="billing_provider_evt_idx")]


class PixCharge(TimeStampedModel):
    public_id=models.CharField(max_length=32,unique=True)
    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="pix_charges")
    subscription=models.ForeignKey(Subscription,on_delete=models.CASCADE,related_name="pix_charges")
    checkout_session=models.ForeignKey(CheckoutSession,on_delete=models.CASCADE,related_name="pix_charges")
    payment=models.ForeignKey(Payment,on_delete=models.CASCADE,related_name="pix_charges")
    provider_order_id=models.CharField(max_length=190)
    provider_payment_id=models.CharField(max_length=190,blank=True)
    amount=models.DecimalField(max_digits=10,decimal_places=2)
    qr_code=models.TextField(blank=True)
    qr_code_base64=models.TextField(blank=True)
    ticket_url=models.URLField(max_length=1000,blank=True)
    status=models.CharField(max_length=16,default="pending",db_index=True)
    expires_at=models.DateTimeField()
    paid_at=models.DateTimeField(null=True,blank=True)


class SubscriptionPriceChange(TimeStampedModel):
    subscription=models.ForeignKey(Subscription,on_delete=models.CASCADE,related_name="price_changes")
    new_base_price=models.DecimalField("Novo valor base por ciclo",max_digits=10,decimal_places=2,validators=[MinValueValidator(Decimal("0.01"))])
    effective_at=models.DateTimeField("Renovação a partir de")
    reason=models.CharField(max_length=16,choices=[("catalog","Reajuste de catálogo"),("promotion","Fim da promoção")])
    status=models.CharField(max_length=16,choices=[("pending","Agendado"),("applied","Aplicado"),("cancelled","Cancelado")],default="pending")
    applied_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL)
    def __str__(self): return f"{self.subscription} · R$ {self.new_base_price}"
