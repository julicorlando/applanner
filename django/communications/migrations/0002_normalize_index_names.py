from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[("communications","0001_initial")]
    operations=[
        migrations.RenameIndex(model_name="campaignrecipient",old_name="comm_recipient_status_idx",new_name="communicati_tenant__74b21b_idx"),
        migrations.RenameIndex(model_name="marketingdelivery",old_name="comm_delivery_status_idx",new_name="communicati_campaig_965573_idx"),
        migrations.RenameIndex(model_name="notification",old_name="comm_notif_queue_idx",new_name="communicati_status_9490cd_idx"),
        migrations.RenameIndex(model_name="usernotification",old_name="comm_user_notif_idx",new_name="communicati_user_id_e89690_idx"),
    ]
