from django.contrib import admin
from .models import (
    BarberCommand, BarberCommandItem, BarberCommandPayment, BarberQueueEntry,
    ProfessionalCompensationModel, ProfessionalGoal, ProfessionalServiceCommission,
)


class CommandItemInline(admin.TabularInline):
    model=BarberCommandItem
    extra=0


class CommandPaymentInline(admin.TabularInline):
    model=BarberCommandPayment
    extra=0


@admin.register(BarberCommand)
class BarberCommandAdmin(admin.ModelAdmin):
    list_display=("id","tenant","customer","professional","status","total_amount","opened_at","closed_at")
    list_filter=("status","tenant")
    search_fields=("customer__name","professional__name")
    inlines=[CommandItemInline,CommandPaymentInline]


@admin.register(BarberQueueEntry)
class BarberQueueAdmin(admin.ModelAdmin):
    list_display=("customer_name","tenant","service","assigned_professional","status","priority","joined_at")
    list_filter=("status","tenant")
    search_fields=("customer_name","customer_phone")


admin.site.register(ProfessionalServiceCommission)
admin.site.register(ProfessionalCompensationModel)
admin.site.register(ProfessionalGoal)
