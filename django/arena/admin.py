from django.contrib import admin
from .models import (
    ArenaSettings, Court, CourtBlock, CourtHours, Modality, PriceRule,
    Reservation, ReservationFinance, SportsSettings,
)


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display=("name","tenant","unit","active","minimum_minutes","maximum_minutes")
    list_filter=("active","indoor","lighting","tenant")
    search_fields=("name","slug")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display=("public_id","tenant","court","customer_name","starts_at","status","payment_status","total_amount")
    list_filter=("status","payment_status","tenant")
    search_fields=("public_id","customer_name","customer_phone","customer_email")
    date_hierarchy="starts_at"


admin.site.register(SportsSettings)
admin.site.register(ArenaSettings)
admin.site.register(Modality)
admin.site.register(CourtHours)
admin.site.register(PriceRule)
admin.site.register(CourtBlock)
admin.site.register(ReservationFinance)
