"""Gross receipts and invoice-backed forecasts, scoped to development clients."""

from datetime import date
from decimal import Decimal
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from .models import Charge, OnlinePayment


def shift_month(value, offset):
    number = value.year * 12 + value.month - 1 + offset
    year, month = divmod(number, 12)
    return date(year, month + 1, 1)


def money_total(condition):
    return Sum("amount", filter=condition, default=Decimal("0.00"))


def financial_report(month, client=None, today=None):
    today = today or timezone.localdate()
    month = month.replace(day=1)
    end = shift_month(month, 1)
    horizon = shift_month(month, 12)
    disputed = OnlinePayment.objects.filter(
        charge_id=OuterRef("pk"), status__in=["refunded", "attention"]
    )
    base = Charge.objects.all()
    if client:
        base = base.filter(client=client)
    base = base.annotate(needs_review=Exists(disputed))
    rows = base.filter(needs_review=False).exclude(status="cancelled")
    paid = Q(status="paid")
    opened = Q(status="open")
    due = opened & Q(due_date__gte=today)
    late = opened & Q(due_date__lt=today)
    paid_month = paid & Q(paid_at__date__gte=month, paid_at__date__lt=end)
    due_month = due & Q(due_date__gte=month, due_date__lt=end)
    totals = rows.aggregate(
        received=money_total(paid),
        received_month=money_total(paid_month),
        to_receive=money_total(opened),
        due=money_total(due),
        overdue=money_total(late),
        due_month=money_total(due_month),
        undated_paid=Count("pk", filter=paid & Q(paid_at__isnull=True)),
        charge_count=Count("pk"),
    )
    totals["forecast_month"] = totals["received_month"] + totals["due_month"]
    totals["review_count"] = base.filter(needs_review=True).count()
    received = {
        row["period"].date(): row["total"]
        for row in rows.filter(
            status="paid", paid_at__date__gte=month, paid_at__date__lt=horizon
        )
        .annotate(period=TruncMonth("paid_at"))
        .values("period")
        .annotate(total=Sum("amount"))
    }
    scheduled = {
        row["period"]: row
        for row in rows.filter(status="open", due_date__gte=month, due_date__lt=horizon)
        .annotate(period=TruncMonth("due_date"))
        .values("period")
        .annotate(
            due=money_total(Q(due_date__gte=today)),
            overdue=money_total(Q(due_date__lt=today)),
        )
    }
    months = []
    for offset in range(12):
        period = shift_month(month, offset)
        actual = received.get(period, Decimal("0.00"))
        upcoming = scheduled.get(period, {}).get("due", Decimal("0.00"))
        months.append(
            {
                "month": period,
                "received": actual,
                "due": upcoming,
                "overdue": scheduled.get(period, {}).get("overdue", Decimal("0.00")),
                "forecast": actual + upcoming,
            }
        )
    customers = (
        rows.values("client_id", "client__name", "client__active")
        .annotate(
            received=money_total(paid_month),
            due=money_total(due_month),
            overdue=money_total(late),
            to_receive=money_total(opened),
        )
        .order_by("client__name", "client_id")
    )
    return {
        "month": month,
        "today": today,
        "totals": totals,
        "months": months,
        "customers": customers,
        "review": base.filter(needs_review=True)
        .select_related("client")
        .order_by("-pk")[:10],
    }
