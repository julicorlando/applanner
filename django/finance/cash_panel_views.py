"""Painel do caixa do dia (por profissional) e relatório do caixa por período.

As regras continuam nos serviços (clinic_services / clinic_cash); aqui só há leitura dos filtros,
chamadas aos serviços e montagem da tela. Toda escrita passa pelas mesmas permissões da recepção."""
import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from core.audit import append_audit
from core.unit_scope import selected_unit
from scheduling.models import Professional

from . import clinic_services as services
from .cash_overview import PRESETS, MAX_DAYS, STATUS_FILTERS, day_overview, period_report, preset_range
from .clinic_cash import KIND_LABEL
from .models import CashSession
from .reception_permissions import allowed, is_manager


def _date(raw, default):
    try:
        return date.fromisoformat(str(raw)) if raw else default
    except ValueError:
        return default


def _panel_url(day, today):
    base = reverse("clinic-cash-panel")
    return base if day == today else f"{base}?dia={day.isoformat()}"


def _open(request, tenant, unit, day):
    post = request.POST
    professional = None
    if post.get("professional", "").isdigit():
        professional = get_object_or_404(Professional, pk=post["professional"], tenant=tenant, active=True)
    row = services.open_clinic_cash(request.user, unit, post.get("opening") or "0", (post.get("notes") or "").strip(),
                                    professional=professional, day=day)
    messages.success(request, f"{row.label} aberto para {day:%d/%m/%Y}.")


def _close(request, tenant, unit):
    post = request.POST
    session = get_object_or_404(CashSession, pk=post.get("session") or 0, tenant=tenant, deleted_at__isnull=True)
    counted = {kind: post.get(f"counted_{kind}") or "0" for kind in ("pix", "card")}
    row = services.close_clinic_cash(user=request.user, unit=unit, amount=post.get("counted_cash") or "0",
                                     notes=(post.get("notes") or "").strip(), session_id=session.pk, counted=counted)
    divergent = (row.clinical_closing.summary or {}).get("divergent")
    if divergent:
        messages.warning(request, f"{row.label} fechado com divergência em "
                                  f"{', '.join(KIND_LABEL[k] for k in divergent)}. A observação ficou registrada.")
    else:
        messages.success(request, f"{row.label} fechado e conferido.")


@login_required
@never_cache
def cash_panel(request):
    tenant = services.access(request.user)
    unit = selected_unit(request, tenant)
    today = services.business_today(tenant)
    day = min(_date(request.GET.get("dia") or request.POST.get("dia"), today), today)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "open":
                _open(request, tenant, unit, day)
            elif action == "close":
                _close(request, tenant, unit)
            else:
                raise PermissionDenied
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        return redirect(_panel_url(day, today))
    data = day_overview(tenant=tenant, unit=unit, day=day, today=today)
    return render(request, "finance/cash_panel.html", {
        **data, "unit": unit, "today_url": reverse("clinic-cash-panel"),
        "can_open_close": allowed(request.user, "abrir_fechar"),
        "can_expense": allowed(request.user, "despesas"),
        # Opening on an earlier day follows the front desk's "dias anteriores" switch.
        "can_open_here": allowed(request.user, "abrir_fechar") and (data["is_today"] or allowed(request.user, "dias_anteriores")),
        "can_past": allowed(request.user, "dias_anteriores"),
        "gestor": is_manager(request.user),
        "professionals": Professional.objects.filter(tenant=tenant, active=True).order_by("name"),
    })


def _report_filters(request, today):
    preset = request.GET.get("periodo", "")
    start, end = preset_range(preset or "mes", today)
    if not preset and (request.GET.get("de") or request.GET.get("ate")):
        start, end = _date(request.GET.get("de"), start), _date(request.GET.get("ate"), end)
        preset = "personalizado"
    end = min(end, today)
    if start > end:
        start, end = end, start
    if (end - start).days >= MAX_DAYS:
        start = end.replace(year=end.year - 1)
    return {"preset": preset or "mes", "start": start, "end": end,
            "professional": request.GET.get("profissional", ""), "status": request.GET.get("status", ""),
            "kind": request.GET.get("forma", "") if request.GET.get("forma", "") in KIND_LABEL else ""}


@login_required
@never_cache
def cash_report(request):
    tenant = services.access(request.user)
    unit = selected_unit(request, tenant)
    today = services.business_today(tenant)
    filters = _report_filters(request, today)
    data = period_report(tenant=tenant, unit=unit, today=today, start=filters["start"], end=filters["end"],
                         professional=filters["professional"], status=filters["status"], kind=filters["kind"])
    append_audit(tenant=tenant, user=request.user, request=request, action="clinic.cash_report.viewed",
                 entity_type="Tenant", entity_id=tenant.pk,
                 after={"from": filters["start"], "to": filters["end"], "export": request.GET.get("formato") == "csv"})
    if request.GET.get("formato") == "csv":
        return _csv(data, filters)
    query = request.GET.copy()
    query["formato"] = "csv"
    return render(request, "finance/cash_report.html", {
        **data, "filters": filters, "presets": PRESETS, "status_filters": STATUS_FILTERS,
        "kinds": list(KIND_LABEL.items()), "unit": unit, "csv_url": f"?{query.urlencode()}",
        "professionals": Professional.objects.filter(tenant=tenant, active=True).order_by("name"),
    })


def _csv(data, filters):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (f'attachment; filename="caixa-{filters["start"]:%Y%m%d}-'
                                       f'{filters["end"]:%Y%m%d}.csv"')
    response.write("﻿")  # Excel opens UTF-8 with the BOM
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Data", "Caixa", "Situação", "Lançamentos", "Recebido", "Dentista", "Consultório", "Outros",
                     "Dinheiro", "Pix", "Débito/Crédito", "Despesas", "Resultado", "Retiradas (sangria)", "Em aberto",
                     "Diferença na gaveta"])
    brl = lambda value: "" if value is None else f"{value:.2f}".replace(".", ",")
    for row in data["sheets"]:
        writer.writerow([f"{row['day']:%d/%m/%Y}", row["label"], row["status_label"], row["lines"], brl(row["received"]),
                         brl(row["dentist"]), brl(row["clinic"]), brl(row["other"]), brl(row["kinds"]["cash"]),
                         brl(row["kinds"]["pix"]), brl(row["kinds"]["card"]), brl(row["expenses"]), brl(row["net"]),
                         brl(row["withdrawals"]), brl(row["open_total"]), brl(row["difference"])])
    return response
