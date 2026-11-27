from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from tenants.models import Tenant
from scheduling.models import Appointment, Customer, Professional, Service
from .portal import _require_tenant, available_modules


@login_required
@never_cache
def search(request):
    term = request.GET.get("q", "").strip()[:100]
    results = []
    if request.user.is_superuser and request.path.startswith("/master/"):
        if len(term) >= 2:
            results = platform_results(term)
        return render(
            request,
            "portal/search.html",
            {"q": term, "results": results, "platform_search": True},
        )
    tenant = _require_tenant(request)
    if not tenant:
        return render(request, "portal/search.html", {"q": term, "results": []})
    if request.user.role in {"professional","healthcare"}:
        professional = get_object_or_404(
            Professional, user=request.user, tenant=tenant, active=True
        )
        if len(term) >= 2:
            rows = (
                Appointment.objects.filter(tenant=tenant, professional=professional)
                .filter(
                    Q(customer__name__icontains=term) | Q(service__name__icontains=term)
                )
                .select_related("customer", "service")
                .order_by("-starts_at")[:30]
            )
            for row in rows:
                results.append(
                    {
                        "title": row.customer_display_name,
                        "kind": row.service.name,
                        "description": row.starts_at,
                        "url": reverse("clinical-patient",args=[row.customer_id]) if request.user.role=="healthcare" else reverse("professional-appointment", args=[row.pk]),
                    }
                )
    elif len(term) >= 2:
        routes = {
            (m["slug"], r["slug"])
            for m in available_modules(request.user, tenant)
            for r in m["resources"]
        }
        if ("agenda", "clientes") in routes:
            for row in (
                Customer.objects.filter(tenant=tenant, active=True)
                .filter(
                    Q(name__icontains=term)
                    | Q(phone__icontains=term)
                    | Q(email__icontains=term)
                )
                .order_by("name")[:20]
            ):
                results.append(
                    {
                        "title": row.name,
                        "kind": "Cliente",
                        "description": "Histórico e preferências",
                        "url": reverse("customer-history", args=[row.pk]),
                    }
                )
        for model, resource, label in [
            (Professional, "profissionais", "Profissional"),
            (Service, "servicos", "Serviço"),
        ]:
            if ("agenda", resource) not in routes:
                continue
            for row in model.objects.filter(
                tenant=tenant, active=True, name__icontains=term
            ).order_by("name")[:20]:
                results.append(
                    {
                        "title": row.name,
                        "kind": label,
                        "description": str(row),
                        "url": reverse(
                            "portal-resource-detail", args=["agenda", resource, row.pk]
                        ),
                    }
                )
    return render(
        request, "portal/search.html", {"q": term, "results": results, "tenant": tenant}
    )


def platform_results(term):
    """Master search: companies, users and support tickets, each opening the right Master page."""
    from accounts.models import User
    from operations.models import SupportTicket
    from .audit_labels import role_label
    digits = "".join(c for c in term if c.isdigit())
    company = Q(name__icontains=term) | Q(email__icontains=term) | Q(slug__icontains=term)
    if len(digits) >= 4:
        company |= Q(phone__contains=digits) | Q(document__contains=digits)
    results = [{"title": row.name, "kind": "Empresa", "description": f"{row.get_status_display()} · {row.email or 'sem e-mail'}",
                "url": reverse("master-company-detail", args=[row.pk])}
               for row in Tenant.objects.filter(deleted_at__isnull=True).filter(company).order_by("name")[:25]]
    people = Q(email__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term)
    for user in User.objects.filter(deleted_at__isnull=True).filter(people).select_related("tenant").order_by("email")[:25]:
        if user.tenant_id:
            results.append({"title": user.get_full_name() or user.email, "kind": "Usuário",
                            "description": f"{user.email} · {user.tenant.name} · {role_label(user.role)}",
                            "url": reverse("master-company-detail", args=[user.tenant_id]) + "?aba=acessos"})
    for ticket in SupportTicket.objects.filter(Q(protocol__icontains=term) | Q(subject__icontains=term)).select_related("tenant").order_by("-created_at")[:15]:
        results.append({"title": f"{ticket.protocol} · {ticket.subject}", "kind": "Chamado",
                        "description": f"{ticket.tenant.name} · {ticket.get_status_display()}",
                        "url": reverse("master-support-ticket", args=[ticket.pk])})
    return results
