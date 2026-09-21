from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class Module(models.Model):
    slug=models.SlugField(max_length=80,unique=True)
    name=models.CharField(max_length=120)
    description=models.CharField(max_length=500,blank=True)
    addon_monthly_price=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    addon_sellable=models.BooleanField(default=False)
    sort_order=models.SmallIntegerField(default=0)
    active=models.BooleanField(default=True)

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
    trial_days=models.PositiveSmallIntegerField(default=14)
    trial_without_card=models.BooleanField(default=True)
    active=models.BooleanField(default=True)
    featured=models.BooleanField(default=False)
    sort_order=models.SmallIntegerField(default=0)
    features=models.JSONField(default=dict,blank=True)
    modules=models.ManyToManyField(Module,through="PlanModule",related_name="plans",blank=True)


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
    status=models.CharField(max_length=20,choices=Status.choices,default=Status.TRIAL,db_index=True)
    started_at=models.DateTimeField()
    trial_started_at=models.DateTimeField(null=True,blank=True)
    trial_ends_at=models.DateTimeField(null=True,blank=True)
    trial_days_snapshot=models.PositiveSmallIntegerField(null=True,blank=True)
    next_billing_at=models.DateTimeField(null=True,blank=True,db_index=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)
    provider_customer_id=models.CharField(max_length=190,blank=True)
    provider_subscription_id=models.CharField(max_length=190,blank=True,db_index=True)
    provider_plan_id=models.CharField(max_length=190,blank=True)


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
        REFUNDED="refunded","Estornado"
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

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="module_addons")
    module=models.ForeignKey(Module,on_delete=models.PROTECT,related_name="addons")
    module_request=models.ForeignKey(ModuleRequest,null=True,blank=True,on_delete=models.SET_NULL,related_name="addons")
    monthly_price=models.DecimalField(max_digits=10,decimal_places=2)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    provider=models.CharField(max_length=40,blank=True)
    provider_reference=models.CharField(max_length=190,blank=True)
    started_at=models.DateTimeField(null=True,blank=True)
    next_billing_at=models.DateTimeField(null=True,blank=True)
    cancelled_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","module"],name="uq_tenant_module_addon")]
