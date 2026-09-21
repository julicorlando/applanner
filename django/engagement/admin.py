from django.contrib import admin
from .models import (
    CustomerMembership, CustomerPackage, LoyaltyAccount, LoyaltyReward,
    ServicePackage, TenantDomain, TenantLoyaltySettings, WaitlistEntry,
)

admin.site.register(ServicePackage)
admin.site.register(CustomerPackage)
admin.site.register(CustomerMembership)
admin.site.register(TenantLoyaltySettings)
admin.site.register(LoyaltyAccount)
admin.site.register(LoyaltyReward)
admin.site.register(WaitlistEntry)
admin.site.register(TenantDomain)
