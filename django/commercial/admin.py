from django.contrib import admin
from .models import CommercialCommission, CommercialProfile, Lead, Proposal

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display=("name","business_type","status","assigned_to","estimated_value","created_at")
    list_filter=("status","business_type","do_not_contact")
    search_fields=("name","email","phone")

@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display=("title","commercial_user","plan","final_price","status","approval_status","expires_at")
    list_filter=("status","approval_status")

admin.site.register(CommercialProfile)
admin.site.register(CommercialCommission)
