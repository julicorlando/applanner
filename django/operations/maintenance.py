from django.shortcuts import render

from .models import PlatformOperationSettings


class MaintenanceModeMiddleware:
    """Keep public traffic safe during planned maintenance without stopping webhooks or Master."""

    ALWAYS_ALLOWED_PREFIXES=(
        "/status/","/healthz/","/livez/","/readyz/",
        "/static/","/imagens/","/webhooks/",
        "/master/","/account/",
    )

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        try:
            config=PlatformOperationSettings.objects.filter(pk=1).only(
                "maintenance_enabled","maintenance_message"
            ).first()
        except Exception:
            config=None
        enabled=bool(config and config.maintenance_enabled)
        if enabled:
            allowed=(
                request.user.is_authenticated and request.user.is_superuser
            ) or request.path.startswith(self.ALWAYS_ALLOWED_PREFIXES)
            if not allowed:
                response=render(request,"operations/maintenance.html",{
                    "maintenance_message":config.maintenance_message,
                },status=503)
                response["Retry-After"]="300"
                response["Cache-Control"]="no-store"
                return response
        return self.get_response(request)
