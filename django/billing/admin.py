from django.contrib import admin
from .models import Payment, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display=("name","slug","monthly_price","active")
    list_filter=("active",)
    search_fields=("name","slug")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display=("tenant","plan","status","started_at","next_billing_at")
    list_filter=("status","plan")
    search_fields=("tenant__name",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display=("tenant","provider","provider_reference","amount","status","paid_at")
    list_filter=("status","provider")
    search_fields=("tenant__name","provider_reference")
