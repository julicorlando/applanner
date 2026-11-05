"""Clinic operations reuse the company financial ledger and cash sessions."""
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


class ClinicPaymentMethod(TimeStampedModel):
    tenant=models.ForeignKey('tenants.Tenant',on_delete=models.CASCADE)
    name=models.CharField(max_length=60)
    kind=models.CharField(max_length=12,choices=[('cash','Dinheiro'),('pix','Pix'),('card','Cartão')])
    active=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['tenant','name'],name='uq_clinic_payment_name')]
    def __str__(self): return self.name


class ClinicCharge(TimeStampedModel):
    professional=models.ForeignKey('scheduling.Professional',on_delete=models.PROTECT,null=True,blank=True,related_name='clinical_charges')
    tenant=models.ForeignKey('tenants.Tenant',on_delete=models.PROTECT)
    unit=models.ForeignKey('tenants.Unit',null=True,blank=True,on_delete=models.PROTECT)
    customer=models.ForeignKey('scheduling.Customer',on_delete=models.PROTECT)
    created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    description=models.CharField(max_length=190)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    request_id=models.UUIDField()
    class Meta:
        constraints=[models.UniqueConstraint(fields=['tenant','request_id'],name='uq_clinic_charge_request')]


    @property
    def balance(self):
        return self.amount-self.received_total


class ClinicInstallment(models.Model):
    charge=models.ForeignKey(ClinicCharge,on_delete=models.PROTECT,related_name='installments')
    number=models.PositiveSmallIntegerField()
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    due_at=models.DateField()
    pending_transaction=models.OneToOneField('finance.FinancialTransaction',on_delete=models.PROTECT)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['charge','number'],name='uq_clinic_installment')]
    @property
    def remaining(self):
        from django.db.models import Sum
        paid=getattr(self,'received_sum',None)
        return self.amount-(paid if paid is not None else self.receipts.aggregate(v=Sum('amount'))['v'] or 0)


class ClinicReceipt(TimeStampedModel):
    installment=models.ForeignKey(ClinicInstallment,on_delete=models.PROTECT,related_name='receipts')
    session=models.ForeignKey('finance.CashSession',on_delete=models.PROTECT,related_name='clinical_receipts')
    method=models.ForeignKey(ClinicPaymentMethod,on_delete=models.PROTECT)
    method_name=models.CharField(max_length=60)
    amount=models.DecimalField(max_digits=12,decimal_places=2)
    transaction=models.OneToOneField('finance.FinancialTransaction',on_delete=models.PROTECT)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    request_id=models.UUIDField(unique=True)


class ClinicExpense(TimeStampedModel):
    review_status=models.CharField(max_length=12,default='pending',choices=[('pending','Aguardando validação'),('approved','Validada'),('questioned','Requer esclarecimento')])
    reviewed_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='reviewed_clinic_expenses')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_note=models.CharField(max_length=500,blank=True)
    method=models.ForeignKey(ClinicPaymentMethod,on_delete=models.PROTECT)
    method_name=models.CharField(max_length=60)
    session=models.ForeignKey('finance.CashSession',on_delete=models.PROTECT,related_name='clinical_expenses')
    transaction=models.OneToOneField('finance.FinancialTransaction',on_delete=models.PROTECT)
    recorded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    invoice_number=models.CharField(max_length=80,blank=True)
    items=models.TextField(max_length=3000,blank=True)
    receipt_encrypted=models.BinaryField(blank=True,default=bytes)
    receipt_mime=models.CharField(max_length=30,blank=True)
    request_id=models.UUIDField(unique=True)


class ClinicCashClosing(models.Model):
    session=models.OneToOneField('finance.CashSession',on_delete=models.PROTECT,related_name='clinical_closing')
    summary=models.JSONField()
