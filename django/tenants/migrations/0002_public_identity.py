from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[("tenants","0001_initial")]
    operations=[
        migrations.AddField(model_name="tenant",name="public_slug",field=models.SlugField(blank=True,max_length=120,null=True,unique=True)),
        migrations.AddField(model_name="tenant",name="public_short_code",field=models.CharField(blank=True,max_length=16,null=True,unique=True)),
        migrations.AddField(model_name="tenant",name="public_booking_enabled",field=models.BooleanField(default=True)),
        migrations.AddField(model_name="tenant",name="category",field=models.CharField(blank=True,max_length=60)),
        migrations.AddField(model_name="tenant",name="default_locale",field=models.CharField(default="pt-br",max_length=10)),
        migrations.AddField(model_name="tenant",name="public_layout",field=models.CharField(default="editorial",max_length=24)),
        migrations.AddField(model_name="tenant",name="public_headline",field=models.CharField(blank=True,max_length=120)),
        migrations.AddField(model_name="tenant",name="public_subheadline",field=models.CharField(blank=True,max_length=300)),
        migrations.AddField(model_name="tenant",name="public_cta_label",field=models.CharField(blank=True,max_length=60)),
        migrations.AddField(model_name="tenant",name="public_announcement",field=models.CharField(blank=True,max_length=160)),
        migrations.AddField(model_name="tenant",name="public_accent_color",field=models.CharField(blank=True,max_length=7)),
        migrations.AddField(model_name="tenant",name="public_section_order",field=models.JSONField(blank=True,default=list)),
        migrations.AddField(model_name="tenant",name="public_seo_title",field=models.CharField(blank=True,max_length=70)),
        migrations.AddField(model_name="tenant",name="public_seo_description",field=models.CharField(blank=True,max_length=180)),
        migrations.AddField(model_name="tenant",name="public_instagram",field=models.CharField(blank=True,max_length=120)),
    ]
