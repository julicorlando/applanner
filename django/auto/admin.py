from django.contrib import admin
from .models import (
    AutoCommand, CRMEvent, Estimate, Job, ServiceBay, Vehicle, VehicleMaintenance,
)

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display=("id","tenant","vehicle","bay","status","expected_ready_at","created_at")
    list_filter=("status","tenant")
    search_fields=("vehicle__plate","vehicle__customer__name")

admin.site.register(Vehicle)
admin.site.register(ServiceBay)
admin.site.register(Estimate)
admin.site.register(AutoCommand)
admin.site.register(VehicleMaintenance)
admin.site.register(CRMEvent)
