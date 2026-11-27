"""Master: what needs attention today, the companies board and the company page tabs."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, Max, OuterRef, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from billing.models import Payment
from operations.models import SupportTicket
from scheduling.models import Appointment
from tenants.models import Tenant

from .audit_labels import CATEGORIES, category, describe
from .master import _guard

OPEN_TICKETS = ["open", "in_progress", "waiting_user"]
STALE_DAYS = 14


def attention():
    """Everything on the home page that asks the Master to act, with where to act."""
    from .master_console import alert_rows, latest_subscriptions
    now = timezone.now()
    items = [{"level": r["level"], "title": r["title"], "count": r["count"], "url": r["url"], "detail": r.get("detail", "")}
             for r in alert_rows()]
    ending = latest_subscriptions().filter(status="trial", trial_ends_at__gte=now, trial_ends_at__lte=now + timedelta(days=3)).count()
    if ending:
        items.append({"level": "warning", "title": "Testes grátis terminando em até 3 dias", "count": ending,
                      "url": reverse("master-companies") + "?situacao=teste-vencendo", "detail": "Converse com a empresa antes do fim do teste."})
    tickets = SupportTicket.objects.filter(status__in=OPEN_TICKETS, tenant__deleted_at__isnull=True).count()
    if tickets:
        items.append({"level": "warning", "title": "Chamados de suporte em aberto", "count": tickets,
                      "url": reverse("master-resource-list", args=["suporte"]), "detail": "Inclui chamados aguardando resposta do usuário."})
    stale_count = stale(board_queryset().filter(status__in=["active", "trial"])).count()
    if stale_count:
        items.append({"level": "warning", "title": f"Empresas sem uso há {STALE_DAYS} dias", "count": stale_count,
                      "url": reverse("master-companies") + "?situacao=parada", "detail": "Sem entrada de usuários nem agendamentos no período."})
    order = {"danger": 0, "warning": 1}
    return sorted(items, key=lambda x: (order.get(x["level"], 2), -x["count"]))


def board_queryset():
    now = timezone.now()
    week = now - timedelta(days=7)
    overdue = Payment.objects.filter(tenant=OuterRef("pk"), purpose="subscription", environment="production",
                                     status="pending", due_at__lt=now)
    return (Tenant.objects.filter(deleted_at__isnull=True, archived_at__isnull=True)
            .annotate(last_login=Max("users__last_login", filter=Q(users__is_superuser=False, users__deleted_at__isnull=True)),
                      bookings_week=Count("appointments", filter=Q(appointments__created_at__gte=week), distinct=True),
                      open_tickets=Count("support_tickets", filter=Q(support_tickets__status__in=OPEN_TICKETS), distinct=True),
                      overdue=Exists(overdue)))


def stale(rows):
    since = timezone.now() - timedelta(days=STALE_DAYS)
    recent_booking = Appointment.objects.filter(tenant=OuterRef("pk"), created_at__gte=since)
    return rows.filter(Q(last_login__lt=since) | Q(last_login__isnull=True)).exclude(Exists(recent_booking))


SITUATIONS = [("", "Todas"), ("teste", "Em teste"), ("teste-vencendo", "Teste terminando"), ("ativa", "Ativas"),
              ("inadimplente", "Com cobrança vencida"), ("parada", f"Sem uso há {STALE_DAYS} dias"),
              ("suporte", "Com chamado aberto"), ("suspensa", "Suspensas")]


@login_required
def companies(request):
    _guard(request.user)
    from .master_console import latest_subscriptions
    rows = board_queryset()
    query = " ".join((request.GET.get("q") or "").split())[:100]
    if query:
        digits = "".join(c for c in query if c.isdigit())
        match = Q(name__icontains=query) | Q(email__icontains=query) | Q(slug__icontains=query) | Q(users__email__icontains=query)
        if len(digits) >= 4:
            match |= Q(phone__contains=digits) | Q(document__contains=digits)
        rows = rows.filter(match).distinct()
    situation = request.GET.get("situacao", "")
    now = timezone.now()
    if situation == "teste":
        rows = rows.filter(status="trial")
    elif situation == "ativa":
        rows = rows.filter(status="active")
    elif situation == "suspensa":
        rows = rows.exclude(status__in=["active", "trial"])
    elif situation == "inadimplente":
        rows = rows.filter(overdue=True)
    elif situation == "parada":
        rows = stale(rows.filter(status__in=["active", "trial"]))
    elif situation == "suporte":
        rows = rows.filter(open_tickets__gt=0)
    elif situation == "teste-vencendo":
        ids = latest_subscriptions().filter(status="trial", trial_ends_at__gte=now, trial_ends_at__lte=now + timedelta(days=3)).values("tenant_id")
        rows = rows.filter(pk__in=ids)
    categories = sorted({c for c in Tenant.objects.filter(deleted_at__isnull=True).values_list("category", flat=True) if c})
    chosen_category = request.GET.get("categoria", "")
    if chosen_category:
        rows = rows.filter(category=chosen_category)
    order = {"nome": "name", "acesso": "-last_login", "agendamentos": "-bookings_week", "cadastro": "-created_at"}
    sort = request.GET.get("ordem", "nome")
    rows = rows.order_by(order.get(sort, "name"), "pk")
    page = Paginator(rows, 50).get_page(request.GET.get("pagina"))
    subs = {s.tenant_id: s for s in latest_subscriptions().filter(tenant_id__in=[r.pk for r in page]).select_related("plan")}
    for row in page:
        row.subscription = subs.get(row.pk)
    params = request.GET.copy()
    params.pop("pagina", None)
    return render(request, "master/companies.html", {
        "page": page, "query": query, "situation": situation, "situations": SITUATIONS, "categories": categories,
        "chosen_category": chosen_category, "sort": sort, "params": params.urlencode(), "stale_days": STALE_DAYS})


TABS = [("geral", "Visão geral"), ("acessos", "Usuários e acessos"), ("plano", "Plano e cobranças"),
        ("clinica", "Clínica"), ("suporte", "Suporte"), ("historico", "Histórico")]


def company_tabs(request, tenant):
    from billing.entitlements import is_healthcare_tenant
    clinic = is_healthcare_tenant(tenant)
    tabs = [(key, label) for key, label in TABS if key != "clinica" or clinic]
    tab = request.GET.get("aba", "geral")
    if tab not in {k for k, _ in tabs}:
        tab = "geral"
    data = {"tabs": tabs, "tab": tab, "is_clinic": clinic}
    if tab == "acessos":
        data["users"] = tenant.users.filter(deleted_at__isnull=True).order_by("-is_active", "email")
    if tab == "clinica":
        from finance.models import CashSession
        from healthcare.document_models import PatientNote
        from scheduling.models import Customer
        data["clinic"] = {
            "patients": Customer.objects.filter(tenant=tenant).count(),
            "imported_notes": PatientNote.objects.filter(tenant=tenant).exclude(import_key="").count(),
            "open_cash": CashSession.objects.filter(tenant=tenant, status="open").select_related("professional").order_by("-opened_at")[:20],
        }
    if tab == "historico":
        from .models import AuditLog
        logs = AuditLog.objects.filter(Q(tenant=tenant) | Q(entity_type__iexact="tenants.Tenant", entity_id=tenant.pk)).select_related("user").order_by("-created_at", "-pk")
        kind = request.GET.get("tipo", "")
        rows = []
        for item in logs[:600]:
            item_kind = category(item.action)
            if kind and item_kind != kind:
                continue
            item.readable = describe(item.action)
            item.kind_label = CATEGORIES.get(item_kind, ("Outros",))[0]
            item.sensitive = item_kind in {"prontuario", "caixa"}
            rows.append(item)
            if len(rows) >= 150:
                break
        data.update({"audit_rows": rows, "audit_kinds": [(k, v[0]) for k, v in CATEGORIES.items()] + [("outros", "Outros")], "audit_kind": kind})
    return data


@login_required
@require_POST
def leave_company(request):
    _guard(request.user)
    request.session.pop("portal_tenant_id", None)
    messages.info(request, "Você saiu do ambiente da empresa.")
    return redirect("master-home")
