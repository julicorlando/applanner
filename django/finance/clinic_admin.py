"""Clinic cash by date and the manager's control of what the front desk may do."""
from collections import OrderedDict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from core.unit_scope import selected_unit

from . import reception_permissions as perms
from .clinic_cash import decide_removal, delete_sheet
from .clinic_models import ClinicCashEntryRemoval
from .clinic_services import access, business_today
from .models import CashSession


@login_required
@never_cache
def cash_days(request):
    """Every cash sheet grouped by day, with the manager's approvals and delete action."""
    tenant = access(request.user)
    unit = selected_unit(request, tenant)
    gestor = perms.is_manager(request.user)
    if request.method == "POST":
        try:
            action = request.POST.get("action", "")
            if action == "delete-sheet" and request.POST.get("session", "").isdigit():
                delete_sheet(user=request.user, session_id=int(request.POST["session"]), reason=request.POST.get("reason", ""))
                messages.success(request, "Caixa apagado. Os lançamentos foram cancelados e ficou registrado na auditoria.")
            elif action in {"approve-removal", "reject-removal"} and request.POST.get("removal", "").isdigit():
                decide_removal(user=request.user, removal_id=int(request.POST["removal"]),
                               approve=action == "approve-removal", note=request.POST.get("note", ""))
                messages.success(request, "Pedido aprovado e lançamento apagado." if action == "approve-removal" else "Pedido recusado.")
            else:
                raise PermissionDenied
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(request.get_full_path())
    today = business_today(tenant)
    try:
        days = max(7, min(int(request.GET.get("dias", 30)), 365))
    except ValueError:
        days = 30
    start = today - timedelta(days=days - 1)
    sheets = (CashSession.objects.filter(tenant=tenant, unit=unit, deleted_at__isnull=True, business_date__gte=start)
              .select_related("professional")
              .annotate(lines=Count("clinical_entries", filter=~Q(clinical_entries__status="cancelled")),
                        received=Sum("clinical_entries__total", filter=Q(clinical_entries__status="paid")))
              .order_by("-business_date", "professional__name"))
    grouped = OrderedDict()
    for sheet in sheets:
        day = grouped.setdefault(sheet.business_date, {"day": sheet.business_date, "sheets": [], "total": 0, "open": 0})
        day["sheets"].append(sheet)
        day["total"] += sheet.received or 0
        day["open"] += sheet.status == "open"
    removals = ClinicCashEntryRemoval.objects.filter(entry__session__tenant=tenant, status="requested").select_related(
        "entry__session__professional", "entry__customer", "requested_by")
    return render(request, "finance/clinic_cash_days.html", {
        "groups": list(grouped.values()), "days": days, "gestor": gestor, "removals": removals, "today": today})


@login_required
@never_cache
def reception_settings(request):
    tenant = access(request.user)
    if not perms.is_manager(request.user):
        raise PermissionDenied("Somente o gestor da empresa define as permissões da recepção.")
    if request.method == "POST":
        perms.save(tenant, request.user, {key: request.POST.get(key) == "on" for key, _, _ in perms.PERMISSIONS}, request)
        messages.success(request, "Permissões da recepção salvas. Valem a partir do próximo clique da recepção.")
        return redirect("clinic-reception-permissions")
    values = perms.current(tenant)
    rows = [{"key": key, "label": label, "on": values[key], "default": default} for key, label, default in perms.PERMISSIONS]
    from accounts.models import User
    team = User.objects.filter(tenant=tenant, role="reception", is_active=True, deleted_at__isnull=True).order_by("email")
    return render(request, "finance/clinic_reception_permissions.html", {"rows": rows, "team": team})
