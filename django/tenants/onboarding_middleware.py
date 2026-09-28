from django.shortcuts import redirect

from .models import TenantOnboarding


class IncompleteOnboardingMiddleware:
    """New tenants finish setup before accessing dashboards or scheduling APIs."""

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,"user",None)
        if (user and user.is_authenticated and user.tenant_id and not user.is_superuser
            and (request.path=="/" or request.path.startswith(("/app/","/api/scheduling/")))):
            if TenantOnboarding.objects.filter(tenant_id=user.tenant_id,required=True,completed_at__isnull=True).exists():
                return redirect("tenant-onboarding")
        return self.get_response(request)
