from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[("scheduling","0001_initial")]
    operations=[
        migrations.AddField(model_name="professional",name="public_slug",field=models.SlugField(blank=True,max_length=120,null=True)),
        migrations.AddField(model_name="professional",name="email",field=models.EmailField(blank=True,max_length=254)),
        migrations.AddField(model_name="professional",name="phone",field=models.CharField(blank=True,max_length=32)),
        migrations.AddField(model_name="professional",name="specialty",field=models.CharField(blank=True,max_length=150)),
        migrations.AddField(model_name="professional",name="photo",field=models.ImageField(blank=True,upload_to="professionals/")),
        migrations.AddField(model_name="professional",name="commission_percent",field=models.DecimalField(blank=True,decimal_places=2,max_digits=5,null=True)),
        migrations.CreateModel(
            name="ProfessionalService",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("professional",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to="scheduling.professional")),
                ("service",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to="scheduling.service")),
            ],
        ),
        migrations.AddField(
            model_name="professional",
            name="services",
            field=models.ManyToManyField(blank=True,related_name="professionals",through="scheduling.ProfessionalService",to="scheduling.service"),
        ),
        migrations.AddConstraint(model_name="professional",constraint=models.UniqueConstraint(fields=("tenant","public_slug"),name="uq_professional_public_slug")),
        migrations.AddConstraint(model_name="professionalservice",constraint=models.UniqueConstraint(fields=("professional","service"),name="uq_professional_service")),
    ]
