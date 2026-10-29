"""One tenant-scoped physiotherapy workspace, independent of individual views."""

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from accounts.permissions import has_capability
from billing.entitlements import module_enabled
from scheduling.models import Professional


def is_physiotherapy(tenant):
    return bool(
        tenant
        and (
            (tenant.category or "").strip().lower() == "fisioterapia"
            or module_enabled(tenant, "physiotherapy")
        )
    )


def workspace_enabled(request):
    user = getattr(request, "user", None)
    if (
        not user
        or not user.is_authenticated
        or not user.is_active
        or user.is_superuser
        or not user.tenant_id
    ):
        return False
    if user.role.startswith("master") or user.role == "commercial":
        return False
    path = request.path
    private = path == "/" or path.startswith(
        ("/app/", "/billing/", "/account/", "/legal/privacidade/meus-dados/")
    )
    return bool(private and is_physiotherapy(user.tenant))


def resource_routes(user):
    from core.portal import available_modules

    return {
        (m["slug"], r["slug"])
        for m in available_modules(user, user.tenant)
        for r in m["resources"]
    }


def shell_context(user, request=None):
    from .services import assert_clinical_access
    from .finance_views import allowed

    profile = (
        Professional.objects.filter(tenant_id=user.tenant_id, user=user, active=True)
        .select_related("clinical_registration")
        .first()
    )
    registration = getattr(profile, "clinical_registration", None) if profile else None
    identity = (
        (registration.professional_name if registration else "")
        or user.get_full_name()
        or (profile.name if profile else user.email)
    )
    try:
        assert_clinical_access(user)
        clinical = True
    except PermissionDenied:
        clinical = False
    routes = resource_routes(user)
    management = user.role in {"owner", "manager", "tenant-admin"}
    agenda = has_capability(user, "agenda.manage")
    patient_url = (
        (
            reverse("professional-search")
            if user.role == "professional"
            else reverse("portal-resource-list", args=["agenda", "clientes"])
        )
        if ("agenda", "clientes") in routes
        else None
    )
    finance_url = (
        reverse("portal-resource-list", args=["financeiro", "lancamentos"])
        if ("financeiro", "lancamentos") in routes
        else reverse("clinical-finance")
        if allowed(user)
        else None
    )
    clinical_url = (
        reverse("physio-assessments")
        if clinical and module_enabled(user.tenant, "medical_records")
        else reverse("clinical-dashboard")
        if user.role in {"owner", "tenant-admin"}
        else None
    )
    rows = [
        ("Dashboard", reverse("physio-dashboard"), "dashboard"),
        ("Agenda", reverse("operation-calendar") if agenda else None, "calendar"),
        ("Pacientes", patient_url, "users"),
        (
            "Atendimentos",
            reverse("professional-area")
            if user.role == "professional"
            else reverse("operation-today")
            if agenda
            else None,
            "record",
        ),
        ("Fisioterapia", clinical_url, "physio"),
        ("Financeiro", finance_url, "money"),
        (
            "Relatórios",
            reverse("operation-performance") if management and agenda else None,
            "report",
        ),
        ("Configurações", reverse("physio-settings"), "settings"),
    ]
    path = request.path if request else reverse("physio-assessments")
    name = (
        getattr(getattr(request, "resolver_match", None), "url_name", "")
        if request
        else ""
    )
    if name in {"physio-dashboard", "portal-home"} or path == "/":
        active = "Dashboard"
    elif name in {
        "operation-calendar",
        "professional-blocks",
        "operation-calendar-move",
    }:
        active = "Agenda"
    elif (
        name in {"clinical-patient", "customer-history"}
        or "/agenda/clientes/" in path
        or name in {"operation-search", "professional-search"}
    ):
        active = "Pacientes"
    elif (
        name
        in {
            "operation-today",
            "professional-area",
            "professional-appointment",
            "reception-appointment",
        }
        or "/agenda/agendamentos/" in path
    ):
        active = "Atendimentos"
    elif name in {"operation-performance", "booking-funnel"}:
        active = "Relatórios"
    elif "/financeiro/" in path or name == "clinical-finance":
        active = "Financeiro"
    elif path.startswith("/app/clinica/") and name not in {"clinical-registration"}:
        active = "Fisioterapia"
    else:
        active = "Configurações"
    locked = bool(request and getattr(request, "billing_locked", False))
    menu = []
    for title, url, icon in rows:
        if locked:
            url = (
                reverse("billing-subscription-status")
                if title == "Financeiro"
                else "/account/2fa/setup/"
                if title == "Configurações"
                else None
            )
        menu.append(
            {
                "title": title,
                "url": url,
                "icon": icon,
                "active": title == ("Financeiro" if locked else active),
            }
        )
    role_label = {
        "reception": "Recepção",
        "owner": "Gestão da clínica",
        "manager": "Gestão da clínica",
        "tenant-admin": "Gestão da clínica",
        "finance": "Financeiro",
    }.get(user.role, "Fisioterapeuta" if clinical else "Equipe da clínica")
    return {
        "physio_identity": identity,
        "physio_photo": profile.photo.url if profile and profile.photo else "",
        "physio_role_label": role_label,
        "physio_menu": menu,
        "physio_search_url": reverse(
            "professional-search" if user.role == "professional" else "operation-search"
        ),
        "physio_notifications_url": reverse(
            "professional-notification-preferences"
            if user.role == "professional"
            else "user-notification-preferences"
        ),
        "physio_clinical_access": clinical,
    }
