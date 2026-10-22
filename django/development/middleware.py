from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from .models import Client


class ClientAccessMiddleware:
    """This new identity can only open its own payment area and account security."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user.role == "development-client":
            if request.path == "/account/logout/":
                return self.get_response(request)
            if (
                user.tenant_id
                or user.is_staff
                or user.is_superuser
                or user.deleted_at
                or not Client.objects.filter(user=user, active=True).exists()
            ):
                raise PermissionDenied
            if request.path in {"/", "/app/", "/account/login/"}:
                return redirect("development-payments")
            allowed = request.path.startswith(
                ("/desenvolvimento/pagamentos/", "/static/", "/imagens/", "/legal/")
            ) or request.path in {
                "/account/logout/",
                "/account/password/change/",
                "/healthz/",
            }
            if not allowed:
                raise PermissionDenied(
                    "Este acesso permite apenas consultar seus próprios pagamentos."
                )
        return self.get_response(request)
