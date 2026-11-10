from django.shortcuts import get_object_or_404
from tenants.models import Unit


def selected_unit(request,tenant):
    key=f"operation_unit_{tenant.pk}"
    raw=request.GET.get("unit")
    if raw is not None:
        if not raw.isdigit():
            raw=None
        else:
            unit=get_object_or_404(Unit,tenant=tenant,active=True,pk=int(raw))
            request.session[key]=unit.pk
            return unit
    stored=request.session.get(key)
    return (Unit.objects.filter(tenant=tenant,active=True,pk=stored).first()
            or tenant.units.filter(active=True).order_by("-is_primary","name").first())


def scope_queryset(qs,unit):
    if unit is None:
        return qs
    names={field.name for field in qs.model._meta.fields}
    if qs.model==Unit:
        return qs.filter(pk=unit.pk)
    if "unit" in names:
        if qs.model._meta.label_lower=="scheduling.service":
            from django.db.models import Q
            return qs.filter(Q(unit=unit)|Q(unit__isnull=True))
        return qs.filter(unit=unit)
    for relation in ("professional","court"):
        if relation in names:
            related=qs.model._meta.get_field(relation).related_model
            if any(field.name=="unit" for field in related._meta.fields):
                return qs.filter(**{f"{relation}__unit":unit})
    return qs


def operation_unit_context(request):
    tenant=getattr(request,"tenant",None)
    if (not tenant or not request.user.is_authenticated or not request.path.startswith("/app/")
            or getattr(request.resolver_match,"url_name",None)=="tenant-branding"):
        return {}
    return {"operation_units":tenant.units.filter(active=True).order_by("-is_primary","name"),
            "operation_selected_unit":selected_unit(request,tenant)}
