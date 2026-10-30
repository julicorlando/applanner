from django.contrib import admin
from .models import Appointment, Customer, Professional, Service


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display=("name","tenant","phone","email","active")
    list_filter=("active","tenant")
    search_fields=("name","phone","email")


@admin.register(Professional)
class ProfessionalAdmin(admin.ModelAdmin):
    list_display=("name","tenant","active","user")
    list_filter=("active","tenant")
    search_fields=("name","user__email")


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display=("name","tenant","duration_minutes","price","active")
    list_filter=("active","tenant")
    search_fields=("name",)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display=("starts_at","tenant","customer","professional","service","status","source")
    list_filter=("status","source","tenant")
    search_fields=("customer__name","professional__name","service__name")
    date_hierarchy="starts_at"
