"""Read-only views of the clinic cash: the day panel (one card per professional) and the period report.

Nothing here writes. Totals come from the same rules as the sheet (clinic_cash.report / expected_cash):
paid lines + installment receipts are income, expenses are outflow, "em aberto" lines are not received.
The period report aggregates in a few queries so a whole year stays fast."""
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .clinic_cash import KIND_LABEL, active_correction, report
from .clinic_models import ClinicCashEntry, ClinicCashEntryRemoval, ClinicCashWithdrawal, ClinicExpense, ClinicReceipt
from .models import CashSession

ZERO = Decimal("0")
KINDS = ("cash", "pix", "card")
STATUS_LABELS = {
    "open": "Aberto",
    "overdue": "Aberto · dia anterior",
    "closed": "Fechado",
    "divergent": "Fechado com divergência",
    "correction": "Em correção",
}
STATUS_FILTERS = (("", "Todos"), ("open", "Abertos"), ("closed", "Fechados sem divergência"),
                  ("divergent", "Com divergência"), ("correction", "Em correção"))


def conference(session):
    """Per-method conference saved at closing ({kind: {expected, informed, difference}}), if any."""
    closing = getattr(session, "clinical_closing", None)
    return ((closing.summary or {}).get("conference") or {}) if closing else {}


def sheet_status(session, today):
    if session.status == CashSession.Status.OPEN:
        return "overdue" if session.business_date and session.business_date < today else "open"
    if active_correction(session):
        return "correction"
    if session.difference_amount or any(Decimal(str(v.get("difference") or 0)) for v in conference(session).values()):
        return "divergent"
    return "closed"


def sheet_card(session, today):
    """Everything the day panel shows for one professional's sheet."""
    data = report(session)
    kinds = dict(zip(KINDS, (value for _, value in data["kinds"])))
    status = sheet_status(session, today)
    lines = sum(1 for row in data["entries"] if row.status != ClinicCashEntry.Status.CANCELLED) + len(data["receipts"])
    return {
        "session": session, "label": session.label, "status": status, "status_label": STATUS_LABELS[status],
        "received": data["columns"]["total"], "dentist": data["columns"]["dentist"], "clinic": data["columns"]["clinic"],
        "other": data["columns"]["other"], "open_total": data["open_total"], "open_count": len(data["open_rows"]),
        "expenses": data["expenses_total"], "net": data["columns"]["total"] - data["expenses_total"],
        "withdrawals": data["withdrawals_total"],
        "drawer_expected": data["drawer_expected"], "kinds": kinds, "lines": lines,
        "conference": conference(session),
        "initials": "".join(word[0] for word in session.label.split()[:2]).upper() or "C",
        "kind_rows": [(kind, KIND_LABEL[kind], kinds[kind]) for kind in KINDS if kinds[kind]],
        "conference_rows": [(KIND_LABEL[kind], conference(session)[kind]) for kind in KINDS if kind in conference(session)],
        # Values the closing modal pre-fills as "esperado" per payment method.
        "expected": {"cash": data["drawer_expected"], "pix": kinds["pix"], "card": kinds["card"]},
        "professionals": data["professionals"],
    }


def _merge_professionals(cards):
    """Soma o "por profissional" de todos os caixas do dia (normalmente um só, o da clínica)."""
    rows = OrderedDict()
    for card in cards:
        for item in card["professionals"]:
            row = rows.setdefault(item["professional"], {k: (ZERO if isinstance(v, Decimal) else 0) for k, v in item.items()
                                                          if k != "professional"} | {"professional": item["professional"]})
            for key, value in item.items():
                if key != "professional":
                    row[key] += value
    return sorted(rows.values(), key=lambda r: (-r["total"], r["professional"]))


def _sum_kinds(cards):
    totals = {kind: ZERO for kind in KINDS}
    for card in cards:
        for kind in KINDS:
            totals[kind] += card["kinds"][kind]
    grand = sum(totals.values(), ZERO)
    return [{"kind": kind, "label": KIND_LABEL[kind], "amount": totals[kind],
             "share": int(round(totals[kind] * 100 / grand)) if grand else 0} for kind in KINDS]


def day_overview(*, tenant, unit, day, today):
    sessions = (CashSession.objects.filter(tenant=tenant, unit=unit, business_date=day, deleted_at__isnull=True)
                .select_related("professional", "tenant", "closed_by", "opened_by", "clinical_closing")
                .order_by("professional__name", "pk"))
    cards = [sheet_card(session, today) for session in sessions]
    # The clinic's own sheet (expenses, unassigned lines) goes last.
    cards.sort(key=lambda c: (c["session"].professional_id is None, c["label"].casefold()))
    with_sheet = {c["session"].professional_id for c in cards}
    day_professionals = _merge_professionals(cards)
    received = sum((c["received"] for c in cards), ZERO)
    expenses = sum((c["expenses"] for c in cards), ZERO)
    removals = (ClinicCashEntryRemoval.objects.filter(entry__session__tenant=tenant, entry__session__unit=unit,
                                                      status=ClinicCashEntryRemoval.Status.REQUESTED)
                .select_related("entry__session__professional", "entry__customer", "requested_by")[:20])
    overdue = (CashSession.objects.filter(tenant=tenant, unit=unit, status="open", deleted_at__isnull=True,
                                          business_date__lt=today)
               .select_related("professional").order_by("business_date")[:30])
    return {
        "day": day, "today": today, "is_today": day == today, "cards": cards,
        "kpis": {
            "received": received, "expenses": expenses, "net": received - expenses,
            "withdrawals": sum((c["withdrawals"] for c in cards), ZERO),
            "open_total": sum((c["open_total"] for c in cards), ZERO),
            "drawer": sum((c["drawer_expected"] for c in cards if c["session"].status == "open"), ZERO),
            "sheets": len(cards), "open": sum(c["session"].status == "open" for c in cards),
            "closed": sum(c["session"].status == "closed" for c in cards),
            "divergent": sum(c["status"] == "divergent" for c in cards),
        },
        "methods": _sum_kinds(cards),
        "day_professionals": day_professionals,
        "clinic_sheet_missing": None not in with_sheet,
        "removals": list(removals), "overdue": list(overdue),
        "yesterday": today - timedelta(days=1), "prev_day": day - timedelta(days=1), "next_day": day + timedelta(days=1) if day < today else None,
    }


# ------------------------------------------------------------------ period report

PRESETS = (("hoje", "Hoje"), ("7d", "Últimos 7 dias"), ("mes", "Este mês"), ("mes-passado", "Mês passado"),
           ("30d", "Últimos 30 dias"))
MAX_DAYS = 366


def preset_range(key, today):
    if key == "hoje":
        return today, today
    if key == "7d":
        return today - timedelta(days=6), today
    if key == "30d":
        return today - timedelta(days=29), today
    if key == "mes-passado":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    return today.replace(day=1), today  # "mes" (default)


def period_report(*, tenant, unit, start, end, today, professional="", status="", kind=""):
    """professional: "" (todos), "clinica" (lançamentos sem profissional) ou o id de um profissional.
    O caixa é um só por dia: o filtro e o "por profissional" vêm de cada linha, despesa e retirada."""
    sessions = (CashSession.objects.filter(tenant=tenant, unit=unit, deleted_at__isnull=True,
                                           business_date__gte=start, business_date__lte=end)
                .select_related("professional", "closed_by", "clinical_closing").order_by("-business_date", "professional__name"))
    rows = OrderedDict()
    for session in sessions:
        state = sheet_status(session, today)
        if status == "open" and session.status != "open":
            continue
        if status in {"closed", "divergent", "correction"} and state != status:
            continue
        rows[session.pk] = {"session": session, "day": session.business_date, "label": session.label,
                            "status": state, "status_label": STATUS_LABELS[state], "received": ZERO, "dentist": ZERO,
                            "clinic": ZERO, "other": ZERO, "open_total": ZERO, "expenses": ZERO, "withdrawals": ZERO, "lines": 0,
                            "kinds": {k: ZERO for k in KINDS}}
    ids = list(rows)
    entries = ClinicCashEntry.objects.filter(session_id__in=ids).exclude(status=ClinicCashEntry.Status.CANCELLED)
    receipts = ClinicReceipt.objects.filter(session_id__in=ids)
    expenses = ClinicExpense.objects.filter(session_id__in=ids).exclude(transaction__status="cancelled")
    withdrawals = ClinicCashWithdrawal.objects.filter(session_id__in=ids, cancelled_at__isnull=True)
    if professional == "clinica":
        entries = entries.filter(professional__isnull=True)
        receipts = receipts.filter(installment__charge__professional__isnull=True)
        expenses = expenses.filter(professional__isnull=True)
        withdrawals = withdrawals.filter(professional__isnull=True)
    elif str(professional).isdigit():
        pid = int(professional)
        entries = entries.filter(professional_id=pid)
        receipts = receipts.filter(installment__charge__professional_id=pid)
        expenses = expenses.filter(professional_id=pid)
        withdrawals = withdrawals.filter(professional_id=pid)
    if kind in KINDS:
        entries = entries.filter(Q(method__kind=kind) | Q(status="open"))
        receipts = receipts.filter(method__kind=kind)
        expenses = expenses.filter(method__kind=kind)
    people = OrderedDict()

    def person(name):
        return people.setdefault(name, {"label": name, "days": set(), "received": ZERO, "dentist": ZERO, "clinic": ZERO,
                                        "other": ZERO, "open_total": ZERO, "expenses": ZERO, "lines": 0, "divergent": 0})
    for item in entries.values("session_id", "session__business_date", "professional_name", "status", "method__kind").annotate(
            n=Count("pk"), total=Sum("total"), dentist=Sum("dentist_amount"), clinic=Sum("clinic_amount"), other=Sum("other_amount")):
        row = rows[item["session_id"]]
        who = person(item["professional_name"] or "Sem profissional informado")
        row["lines"] += item["n"]
        who["lines"] += item["n"]
        who["days"].add(item["session__business_date"])
        if item["status"] == "open":
            if not kind:
                row["open_total"] += item["total"] or ZERO
                who["open_total"] += item["total"] or ZERO
            continue
        row["received"] += item["total"] or ZERO
        who["received"] += item["total"] or ZERO
        row["kinds"][item["method__kind"]] = row["kinds"].get(item["method__kind"], ZERO) + (item["total"] or ZERO)
        for key in ("dentist", "clinic", "other"):
            row[key] += item[key] or ZERO
            who[key] += item[key] or ZERO
    for item in receipts.values("session_id", "session__business_date", "installment__charge__professional__name",
                                "method__kind").annotate(n=Count("pk"), total=Sum("amount")):
        row = rows[item["session_id"]]
        who = person(item["installment__charge__professional__name"] or "Sem profissional informado")
        row["lines"] += item["n"]
        row["received"] += item["total"] or ZERO
        row["kinds"][item["method__kind"]] = row["kinds"].get(item["method__kind"], ZERO) + (item["total"] or ZERO)
        who["lines"] += item["n"]
        who["received"] += item["total"] or ZERO
        who["days"].add(item["session__business_date"])
    for item in expenses.values("session_id", "professional__name").annotate(total=Sum("transaction__amount")):
        rows[item["session_id"]]["expenses"] += item["total"] or ZERO
        if item["professional__name"]:
            person(item["professional__name"])["expenses"] += item["total"] or ZERO
    if kind in ("", None, "cash") or kind not in KINDS:
        for item in withdrawals.values("session_id").annotate(total=Sum("amount")):
            rows[item["session_id"]]["withdrawals"] += item["total"] or ZERO
    sheets = list(rows.values())
    if professional:
        sheets = [r for r in sheets if r["lines"] or r["expenses"] or r["withdrawals"]]
    for row in sheets:
        row["net"] = row["received"] - row["expenses"]
        row["difference"] = row["session"].difference_amount if row["session"].status == "closed" else None
    by_day = OrderedDict()
    for row in sheets:
        d = by_day.setdefault(row["day"], {"day": row["day"], "sheets": 0, "open": 0, "received": ZERO, "expenses": ZERO,
                                           "open_total": ZERO, "divergent": 0})
        d["sheets"] += 1
        d["received"] += row["received"]
        d["expenses"] += row["expenses"]
        d["open_total"] += row["open_total"]
        d["divergent"] += row["status"] == "divergent"
        d["open"] += row["session"].status == "open"
    for d in by_day.values():
        d["net"] = d["received"] - d["expenses"]
    for p in people.values():
        p["sheets"] = len(p.pop("days"))
        p["dentist_net"] = p["dentist"] - p["expenses"]
    professionals = sorted(people.values(), key=lambda r: (-r["received"], r["label"]))
    top = professionals[0]["received"] if professionals else ZERO
    for p in professionals:
        p["share"] = int(round(p["received"] * 100 / top)) if top else 0
    kinds = {k: sum((r["kinds"].get(k, ZERO) for r in sheets), ZERO) for k in KINDS}
    grand = sum(kinds.values(), ZERO)
    received = sum((r["received"] for r in sheets), ZERO)
    spent = sum((r["expenses"] for r in sheets), ZERO)
    return {
        "start": start, "end": end, "sheets": sheets, "by_professional": professionals, "by_day": list(by_day.values()),
        "methods": [{"kind": k, "label": KIND_LABEL[k], "amount": kinds[k],
                     "share": int(round(kinds[k] * 100 / grand)) if grand else 0} for k in KINDS],
        "kpis": {"received": received, "expenses": spent, "net": received - spent,
                 "withdrawals": sum((r["withdrawals"] for r in sheets), ZERO),
                 "open_total": sum((r["open_total"] for r in sheets), ZERO), "sheets": len(sheets),
                 "lines": sum(r["lines"] for r in sheets), "open": sum(r["session"].status == "open" for r in sheets),
                 "divergent": sum(r["status"] == "divergent" for r in sheets),
                 "days": len(by_day), "average": (received / len(by_day)).quantize(Decimal("0.01")) if by_day else ZERO},
    }
