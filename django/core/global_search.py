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
            for row in (
                Tenant.objects.filter(deleted_at__isnull=True, archived_at__isnull=True)
                .filter(Q(name__icontains=term) | Q(email__icontains=term))
                .order_by("name")[:30]
            ):
                results.append(
                    {
                        "title": row.name,
                        "kind": "Empresa",
                        "description": row.get_status_display(),
                        "url": reverse(
                            "master-resource-edit", args=["empresas", row.pk]
                        ),
                    }
                )
        return render(
            request,
            "portal/search.html",
            {"q": term, "results": results, "platform_search": True},
        )
    tenant = _require_tenant(request)
    if not tenant:
        return render(request, "portal/search.html", {"q": term, "results": []})
    if request.user.role == "professional":
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
                        "url": reverse("professional-appointment", args=[row.pk]),
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
