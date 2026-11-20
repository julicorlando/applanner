from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ("auto","0001_initial"),
        ("engagement","0001_initial"),
    ]
    operations=[
        migrations.CreateModel(
            name="VehiclePackageLink",
            fields=[
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("customer_package",models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,related_name="vehicle_link",
                    serialize=False,to="engagement.customerpackage",
                )),
                ("tenant",models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="auto_vehicle_package_links",to="tenants.tenant",
                )),
                ("vehicle",models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="package_links",to="auto.vehicle",
                )),
            ],
        ),
        migrations.AddIndex(
            model_name="vehiclepackagelink",
            index=models.Index(fields=["tenant","vehicle"],name="auto_pkg_vehicle_idx"),
        ),
        migrations.CreateModel(
            name="MembershipVehicleLink",
            fields=[
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("membership",models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    primary_key=True,related_name="vehicle_link",
                    serialize=False,to="engagement.customermembership",
                )),
                ("tenant",models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="auto_membership_vehicle_links",to="tenants.tenant",
                )),
                ("vehicle",models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="membership_links",to="auto.vehicle",
                )),
            ],
        ),
        migrations.AddIndex(
            model_name="membershipvehiclelink",
            index=models.Index(fields=["tenant","vehicle"],name="auto_member_vehicle_idx"),
        ),
    ]
