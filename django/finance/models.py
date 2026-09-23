from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class FinancialCategory(models.Model):
    class Type(models.TextChoices):
        INCOME="income","Receita"
        EXPENSE="expense","Despesa"
        BOTH="both","Ambos"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="financial_categories")
    name=models.CharField(max_length=120)
    type=models.CharField(max_length=12,choices=Type.choices,default=Type.BOTH)
    active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=["tenant","name"],name="uq_financial_category")]


class FinancialTransaction(TimeStampedModel):
    class Type(models.TextChoices):
        INCOME="income","Receita"
        EXPENSE="expense","Despesa"

    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        CANCELLED="cancelled","Cancelado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="financial_transactions")
    appointment=models.ForeignKey("scheduling.Appointment",null=True,blank=True,on_delete=models.SET_NULL,related_name="financial_transactions")
    category=models.ForeignKey(FinancialCategory,null=True,blank=True,on_delete=models.SET_NULL,related_name="transactions")
    source_type=models.CharField(max_length=40,blank=True)
    source_id=models.BigIntegerField(null=True,blank=True)
    type=models.CharField(max_length=12,choices=Type.choices)
    description=models.CharField(max_length=190)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    payment_method=models.CharField(max_length=40,blank=True)
    competence_at=models.DateField(null=True,blank=True)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    idempotency_key=models.CharField(max_length=100,blank=True)
    due_at=models.DateField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["tenant","idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uq_finance_idempotency",
            ),
        ]
        indexes=[
            models.Index(fields=["tenant","status","due_at"]),
            models.Index(fields=["tenant","source_type","source_id"]),
        ]


class Product(TimeStampedModel):
    class CommissionType(models.TextChoices):
        NONE="none","Sem comissão"
        PERCENT="percent","Percentual"
        FIXED="fixed","Fixa"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="products")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="products")
    name=models.CharField(max_length=150)
    sku=models.CharField(max_length=80,blank=True)
    code=models.CharField(max_length=80,blank=True)
    category=models.CharField(max_length=100,blank=True)
    description=models.TextField(blank=True)
    cost_price=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    sale_price=models.DecimalField(max_digits=10,decimal_places=2)
    stock=models.DecimalField(max_digits=12,decimal_places=3,default=0)
    minimum_stock=models.DecimalField(max_digits=12,decimal_places=3,default=0)
    unit_label=models.CharField(max_length=20,default="un")
    commission_type=models.CharField(max_length=12,choices=CommissionType.choices,default=CommissionType.NONE)
    commission_value=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["tenant","sku"],
                condition=~models.Q(sku=""),
                name="uq_product_sku",
            ),
        ]
        indexes=[models.Index(fields=["tenant","active"])]


class Sale(models.Model):
    class Status(models.TextChoices):
        COMPLETED="completed","Concluída"
        CANCELLED="cancelled","Cancelada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="sales")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="sales")
    professional=models.ForeignKey("scheduling.Professional",null=True,blank=True,on_delete=models.SET_NULL,related_name="sales")
    customer=models.ForeignKey("scheduling.Customer",null=True,blank=True,on_delete=models.SET_NULL,related_name="sales")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="sales_created")
    subtotal=models.DecimalField(max_digits=10,decimal_places=2)
    discount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    total=models.DecimalField(max_digits=10,decimal_places=2)
    payment_method=models.CharField(max_length=40)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.COMPLETED)
    cancel_reason=models.CharField(max_length=500,blank=True)
    cancelled_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="sales_cancelled")
    cancelled_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","created_at"])]


class SaleItem(models.Model):
    sale=models.ForeignKey(Sale,on_delete=models.CASCADE,related_name="items")
    product=models.ForeignKey(Product,on_delete=models.PROTECT,related_name="sale_items")
    quantity=models.DecimalField(max_digits=12,decimal_places=3)
    unit_price=models.DecimalField(max_digits=10,decimal_places=2)
    discount=models.DecimalField(max_digits=10,decimal_places=2,default=0)
    total=models.DecimalField(max_digits=10,decimal_places=2)
    cost_snapshot=models.DecimalField(max_digits=10,decimal_places=2)
    commission_amount_snapshot=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)


class ProductStockMovement(models.Model):
    class Type(models.TextChoices):
        SALE="sale","Venda"
        SALE_REVERSAL="sale_reversal","Estorno de venda"
        ADJUSTMENT="adjustment","Ajuste"
        ENTRY="entry","Entrada"
        COMMAND="command","Comanda"
        COMMAND_REVERSAL="command_reversal","Estorno de comanda"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="stock_movements")
    product=models.ForeignKey(Product,on_delete=models.PROTECT,related_name="stock_movements")
    sale=models.ForeignKey(Sale,null=True,blank=True,on_delete=models.SET_NULL,related_name="stock_movements")
    type=models.CharField(max_length=24,choices=Type.choices)
    quantity=models.DecimalField(max_digits=12,decimal_places=3)
    balance_after=models.DecimalField(max_digits=12,decimal_places=3)
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="stock_movements")
    reason=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[models.Index(fields=["product","created_at"])]


class CashSession(models.Model):
    class Status(models.TextChoices):
        OPEN="open","Aberto"
        CLOSED="closed","Fechado"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="cash_sessions")
    unit=models.ForeignKey("tenants.Unit",null=True,blank=True,on_delete=models.SET_NULL,related_name="cash_sessions")
    opened_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="cash_sessions_opened")
    opening_amount=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    opened_at=models.DateTimeField()
    closed_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="cash_sessions_closed")
    closing_amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    expected_amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    difference_amount=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    closed_at=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=12,choices=Status.choices,default=Status.OPEN,db_index=True)
    notes=models.CharField(max_length=500,blank=True)

    class Meta:
        indexes=[models.Index(fields=["tenant","status","opened_at"])]


class ProfessionalCommission(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        REVERSED="reversed","Estornada"

    tenant=models.ForeignKey("tenants.Tenant",on_delete=models.CASCADE,related_name="professional_commissions")
    professional=models.ForeignKey("scheduling.Professional",on_delete=models.CASCADE,related_name="commissions")
    source_type=models.CharField(max_length=32)
    source_id=models.BigIntegerField()
    gross_amount=models.DecimalField(max_digits=12,decimal_places=2)
    rate_percent=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    commission_amount=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    paid_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="commissions_paid")

    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=["tenant","professional","source_type","source_id"],
                name="uq_professional_commission_source",
            ),
        ]
        indexes=[models.Index(fields=["tenant","professional","status","created_at"])]


class PlatformFinanceCategory(TimeStampedModel):
    class Type(models.TextChoices):
        INCOME="income","Receita"
        EXPENSE="expense","Despesa"
        BOTH="both","Ambos"

    name=models.CharField(max_length=120,unique=True)
    type=models.CharField(max_length=12,choices=Type.choices,default=Type.BOTH)
    active=models.BooleanField(default=True)


class PlatformFinancialTransaction(TimeStampedModel):
    class Type(models.TextChoices):
        INCOME="income","Receita"
        EXPENSE="expense","Despesa"
    class Status(models.TextChoices):
        PENDING="pending","Pendente"
        PAID="paid","Pago"
        CANCELLED="cancelled","Cancelado"

    category=models.ForeignKey(PlatformFinanceCategory,null=True,blank=True,on_delete=models.SET_NULL,related_name="transactions")
    type=models.CharField(max_length=12,choices=Type.choices)
    description=models.CharField(max_length=190)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    status=models.CharField(max_length=16,choices=Status.choices,default=Status.PENDING,db_index=True)
    due_at=models.DateField(null=True,blank=True)
    paid_at=models.DateTimeField(null=True,blank=True)
    notes=models.CharField(max_length=500,blank=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="platform_finance_transactions")

    class Meta:
        indexes=[models.Index(fields=["type","status","due_at"],name="platform_finance_status_idx")]


class PlatformBankAccount(TimeStampedModel):
    class AccountType(models.TextChoices):
        CHECKING="checking","Corrente"
        SAVINGS="savings","Poupança"
        PAYMENT="payment","Pagamento"
        BUSINESS="business","Empresarial"
    class PersonType(models.TextChoices):
        INDIVIDUAL="individual","Pessoa física"
        COMPANY="company","Pessoa jurídica"
    class Status(models.TextChoices):
        ACTIVE="active","Ativa"
        INACTIVE="inactive","Inativa"

    bank_name=models.CharField(max_length=120)
    bank_code=models.CharField(max_length=10)
    ispb=models.CharField(max_length=20,blank=True)
    account_type=models.CharField(max_length=16,choices=AccountType.choices)
    agency_encrypted=models.TextField()
    agency_digit=models.CharField(max_length=3,blank=True)
    account_encrypted=models.TextField()
    account_digit=models.CharField(max_length=3,blank=True)
    holder_name=models.CharField(max_length=150)
    holder_document_encrypted=models.TextField()
    person_type=models.CharField(max_length=16,choices=PersonType.choices)
    pix_key_encrypted=models.TextField(blank=True)
    pix_key_type=models.CharField(max_length=12,blank=True)
    currency=models.CharField(max_length=3,default="BRL")
    notes_encrypted=models.TextField(blank=True)
    is_default=models.BooleanField(default=False)
    status=models.CharField(max_length=12,choices=Status.choices,default=Status.ACTIVE,db_index=True)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="platform_bank_accounts")
    deleted_at=models.DateTimeField(null=True,blank=True)

    class Meta:
        indexes=[models.Index(fields=["status","is_default"],name="platform_bank_status_idx")]
        constraints=[
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True,status="active",deleted_at__isnull=True),
                name="uq_platform_default_bank",
            )
        ]


class ProductEvent(models.Model):
    tenant=models.ForeignKey("tenants.Tenant",null=True,blank=True,on_delete=models.SET_NULL,related_name="product_events")
    user=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name="product_events")
    event_type=models.CharField(max_length=80,db_index=True)
    metadata=models.JSONField(default=dict,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes=[
            models.Index(fields=["event_type","created_at"],name="finance_product_evt_idx"),
            models.Index(fields=["tenant","created_at"],name="finance_product_tenant_idx"),
        ]
