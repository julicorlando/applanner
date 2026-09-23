from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[("finance","0001_initial")]
    operations=[
        migrations.RenameIndex(model_name="cashsession",old_name="finance_cash_status_idx",new_name="finance_cas_tenant__c2046f_idx"),
        migrations.RenameIndex(model_name="financialtransaction",old_name="finance_tx_status_due_idx",new_name="finance_fin_tenant__a7a5ad_idx"),
        migrations.RenameIndex(model_name="financialtransaction",old_name="finance_tx_source_idx",new_name="finance_fin_tenant__faff25_idx"),
        migrations.RenameIndex(model_name="product",old_name="finance_product_active_idx",new_name="finance_pro_tenant__7017c2_idx"),
        migrations.RenameIndex(model_name="productstockmovement",old_name="finance_stock_product_idx",new_name="finance_pro_product_924e1c_idx"),
        migrations.RenameIndex(model_name="professionalcommission",old_name="finance_comm_status_idx",new_name="finance_pro_tenant__730298_idx"),
        migrations.RenameIndex(model_name="sale",old_name="finance_sale_created_idx",new_name="finance_sal_tenant__15b09b_idx"),
    ]
