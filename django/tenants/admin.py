from django.contrib import admin
from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display=("name","slug","status","email","created_at")
    list_filter=("status",)
    search_fields=("name","slug","email","document")
    prepopulated_fields={"slug":("name",)}
