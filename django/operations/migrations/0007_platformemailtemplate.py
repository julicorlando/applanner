from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ('operations','0006_platformsmtpsettings'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(name='PlatformEmailTemplate',fields=[
            ('key',models.CharField(max_length=50,primary_key=True,serialize=False)),
            ('subject',models.CharField(max_length=180)),
            ('body',models.TextField(max_length=10000)),
            ('updated_at',models.DateTimeField(auto_now=True)),
            ('updated_by',models.ForeignKey(null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='+',to=settings.AUTH_USER_MODEL)),
        ]),
    ]
