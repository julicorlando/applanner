from zoneinfo import ZoneInfo
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from accounts.permissions import has_capability
from scheduling.models import Appointment, Customer
from .navigation import workspace_enabled, resource_routes, dental_workspace


def tenant_for(request):
    if not workspace_enabled(request):
        raise PermissionDenied("Área exclusiva do estabelecimento de Fisioterapia.")
    return request.user.tenant


@login_required
@never_cache
@require_safe
def dashboard(request):
    tenant = tenant_for(request)
    if getattr(request, "billing_locked", False):
        return redirect("billing-subscription-status")
    from core.operation_insights import day_bounds
    from core.unit_scope import selected_unit, scope_queryset

    today = (
        timezone.now().astimezone(ZoneInfo(tenant.timezone or "America/Recife")).date()
    )
    rows = Appointment.objects.none()
    stats = None
    if has_capability(request.user, "agenda.manage"):
        rows = scope_queryset(
            Appointment.objects.filter(tenant=tenant), selected_unit(request, tenant)
        )
        if request.user.role == "professional":
            rows = rows.filter(professional__user=request.user)
        patient_count = (
            rows.values("customer_id").distinct().count()
            if request.user.role == "professional"
            else Customer.objects.filter(tenant=tenant, active=True).count()
        )
        start, end = day_bounds(tenant, today)
        rows = rows.filter(starts_at__gte=start, starts_at__lt=end)
        stats = {
            "appointments": rows.count(),
            "completed": rows.filter(status="completed").count(),
            "patients": patient_count,
        }
    return render(
        request,
        "healthcare/physio_dashboard.html",
        {
            "tenant": tenant,
            "stats": stats,
            "today": today,
            "appointments": rows.select_related(
                "customer", "professional", "service"
            ).order_by("starts_at")[:100],
        },
    )


@login_required
@never_cache
@require_safe
def settings(request):
    tenant = tenant_for(request)
    from core.portal import PORTAL_MODULES, _role_resource_write

    routes = resource_routes(request.user)
    groups = []
    for slug in ("agenda", "financeiro", "relacionamento", "comunicacao", "suporte"):
        if slug not in PORTAL_MODULES or request.user.role == "professional":
            continue
        links = []
        for resource, config in PORTAL_MODULES[slug]["resources"].items():
            if (slug, resource) in routes:
                links.append(
                    {
                        "title": "Pacientes"
                        if slug == "agenda" and resource == "clientes"
                        else config["title"],
                        "url": reverse("portal-resource-list", args=[slug, resource]),
                        "readonly": not _role_resource_write(
                            request.user, slug, resource
                        ),
                    }
                )
        if links:
            groups.append({"title": PORTAL_MODULES[slug]["title"], "links": links})
    account = [
        {"title": "Segurança da conta", "url": "/account/2fa/setup/"},
        {"title": "Meus dados e privacidade", "url": reverse("legal-privacy-center")},
        {"title": "Documentação e API", "url": reverse("accounts:documentation")},
    ]
    if request.user.role in {"owner", "tenant-admin"}:
        account.extend(
            [
                {
                    "title": "Plano e assinatura",
                    "url": reverse("billing-subscription-status"),
                },
                {"title": "Acesso da recepção", "url": reverse("reception-access")},
                {
                    "title": "Página pública da clínica",
                    "url": reverse("tenant-branding"),
                },
            ]
        )
    from .services import assert_clinical_access

    try:
        assert_clinical_access(request.user)
    except PermissionDenied:
        pass
    else:
        account.append(
            {
                "title": "Identificação profissional e CRO/UF" if dental_workspace(tenant) else "Identificação profissional e CREFITO",
                "url": reverse("clinical-registration"),
            }
        )
    if has_capability(request.user, "agenda.manage") and request.user.role in {
        "owner",
        "manager",
        "tenant-admin",
    }:
        account.extend(
            {"title": title, "url": reverse(route)}
            for title, route in [
                ("Configuração por unidade", "unit-schedule-settings"),
                ("Expedientes em massa", "bulk-work-schedule"),
                ("Primeiros passos", "portal-setup"),
                ("Diagnóstico da operação", "portal-diagnostics"),
            ]
        )
    if request.user.role == "owner":
        account.extend(
            {"title": title, "url": reverse(route)}
            for title, route in [
                ("Recebimentos e integração de pagamentos", "tenant-payment-gateway"),
                ("WhatsApp da clínica", "tenant-whatsapp-settings"),
                ("Avaliações da equipe", "tenant-ratings"),
            ]
        )
    account.append(
        {
            "title": "Notificações neste dispositivo",
            "url": reverse(
                "professional-notification-preferences"
                if request.user.role == "professional"
                else "user-notification-preferences"
            ),
        }
    )
    if tenant.public_enabled:
        account.append(
            {
                "title": "Abrir página pública da clínica",
                "url": reverse(
                    "tenant-public", args=[tenant.public_slug or tenant.slug]
                ),
            }
        )
    groups.append({"title": "Conta e clínica", "links": account})
    return render(
        request,
        "healthcare/physio_settings.html",
        {"tenant": tenant, "settings_groups": groups},
    )
