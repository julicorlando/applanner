from django.db import migrations,models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('finance','0007_financial_transaction_unit'),('billing','0017_subscription_payment_method_and_more')]
    operations=[migrations.AddField(model_name='platformfinancialtransaction',name='provider_fee_payment',
        field=models.OneToOneField('billing.Payment',null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,related_name='manual_provider_fee',
            verbose_name='Pagamento relacionado à taxa do provedor',help_text='Vincule somente uma taxa de pagamento lançada manualmente. Após a conciliação, ela não será descontada duas vezes.'))]
