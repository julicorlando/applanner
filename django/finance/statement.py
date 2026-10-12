from decimal import Decimal
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from accounts.permissions import require_any_capability
from .portal import _tenant
from .models import FinancialTransaction


class PeriodForm(forms.Form):
    start = forms.DateField(label="De", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Até", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        start, end = data.get("start"), data.get("end")
        if start and end and (end < start or (end - start).days > 366):
            raise forms.ValidationError(
                "Escolha um período de até 366 dias, com fim após o início."
            )
        return data


@login_required
def statement(request):
    require_any_capability(request.user, "finance.manage")
    if request.user.role in {"professional", "reception"}:
        raise PermissionDenied
    tenant = _tenant(request)
    today = timezone.localdate()
    defaults = {"start": today.replace(day=1), "end": today}
    form = PeriodForm(request.GET or defaults)
    rows = []
    income = expenses = Decimal("0")
    if form.is_valid():
        qs = FinancialTransaction.objects.filter(
            tenant=tenant,
            competence_at__gte=form.cleaned_data["start"],
            competence_at__lte=form.cleaned_data["end"],
        ).exclude(status="cancelled")
        from core.unit_scope import selected_unit

        unit = selected_unit(request, tenant)
        if unit:
            qs = qs.filter(unit=unit)
        rows = list(
            qs.values("type", "category__name", "status")
            .annotate(total=Sum("amount"))
            .order_by("type", "category__name", "status")
        )
        income = sum(
            (row["total"] for row in rows if row["type"] == "income"), Decimal("0")
        )
        expenses = sum(
            (row["total"] for row in rows if row["type"] == "expense"), Decimal("0")
        )
    return render(
        request,
        "finance/statement.html",
        {
            "tenant": tenant,
            "form": form,
            "rows": rows,
            "income": income,
            "expenses": expenses,
            "result": income - expenses,
        },
    )
