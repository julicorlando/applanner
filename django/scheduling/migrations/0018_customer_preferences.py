from django.db import migrations,models
class Migration(migrations.Migration):
    dependencies=[('scheduling','0017_service_unit')]
    operations=[migrations.AddField(model_name='customer',name='preferences',field=models.CharField(max_length=1000,blank=True))]
