from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.db.models import Q, Sum, F, DecimalField, ExpressionWrapper
from .models import (
    FinancialTransaction,
    SaleItem,
    MaterialConsumption,
    ProfessionalCommission,
)

ZERO = Decimal("0")
LINES = [
    ("gross_revenue", "Receita operacional"),
    ("deductions", "Deduções e tributos sobre receita"),
    ("direct_costs", "Custos diretos"),
    ("operating_expenses", "Despesas operacionais"),
    ("financial_income", "Receitas financeiras"),
    ("financial_expenses", "Despesas financeiras"),
    ("income_tax", "Tributos sobre resultado"),
]


def report(tenant, start, end, unit=None):
    tz = ZoneInfo(tenant.timezone or "America/Recife")
    first = datetime.combine(start, time.min, tz)
    after = datetime.combine(end + timedelta(days=1), time.min, tz)
    amounts = {key: ZERO for key, _ in LINES}
    details = []
    warnings = []
    qs = (
        FinancialTransaction.objects.filter(
            tenant=tenant, competence_at__range=[start, end]
        )
        .exclude(status="cancelled")
        .exclude(source_type="professional_commission")
    )
    if unit:
        qs = qs.filter(unit=unit)
    for row in qs.select_related("category", "unit"):
        line = row.category.statement_line if row.category_id else ""
        if line == "inventory_asset":
            continue
        if not line:
            line = "gross_revenue" if row.type == "income" else "operating_expenses"
            if row.source_type not in {"appointment", "sale", "barber_command"}:
                warnings.append(f"Lançamento #{row.pk} sem classificação na DRE.")
        incoming = line in {"gross_revenue", "financial_income"}
        signed = row.amount if (row.type == "income") == incoming else -row.amount
        amounts[line] += signed
        details.append(
            {
                "label": row.description,
                "line": line,
                "amount": signed,
                "source": f"Lançamento #{row.pk}",
                "nature": row.category.expense_nature if row.category_id else "",
            }
        )
    items = SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__status="completed",
        sale__created_at__gte=first,
        sale__created_at__lt=after,
    )
    from barber.models import BarberCommandItem

    commands = BarberCommandItem.objects.filter(
        tenant=tenant,
        command__status="closed",
        command__closed_at__gte=first,
        command__closed_at__lt=after,
        item_type="product",
    )
    materials = MaterialConsumption.objects.filter(
        tenant=tenant,
        created_at__gte=first,
        created_at__lt=after,
        reversed_at__isnull=True,
    )
    if unit:
        items = items.filter(
            Q(sale__unit=unit)
            | Q(sale__unit__isnull=True, sale__professional__unit=unit)
        )
        commands = commands.filter(
            Q(command__appointment__unit=unit)
            | Q(command__appointment__isnull=True, command__professional__unit=unit)
        )
        materials = materials.filter(
            Q(appointment__unit=unit) | Q(appointment__isnull=True, product__unit=unit)
        )
    from .models import Sale
    from barber.models import BarberCommand

    sales = Sale.objects.filter(
        tenant=tenant, status="completed", created_at__gte=first, created_at__lt=after
    )
    closed = BarberCommand.objects.filter(
        tenant=tenant, status="closed", closed_at__gte=first, closed_at__lt=after
    )
    if unit:
        sales = sales.filter(
            Q(unit=unit) | Q(unit__isnull=True, professional__unit=unit)
        )
        closed = closed.filter(
            Q(appointment__unit=unit)
            | Q(appointment__isnull=True, professional__unit=unit)
        )
    discount = (
        (sales.aggregate(v=Sum("discount"))["v"] or ZERO)
        + (items.aggregate(v=Sum("discount"))["v"] or ZERO)
        + (closed.aggregate(v=Sum("discount_amount"))["v"] or ZERO)
        + (
            BarberCommandItem.objects.filter(command__in=closed).aggregate(
                v=Sum("discount_amount")
            )["v"]
            or ZERO
        )
    )
    amounts["gross_revenue"] += discount
    amounts["deductions"] += discount
    details.append(
        {
            "label": "Descontos concedidos",
            "line": "deductions",
            "amount": discount,
            "source": "Vendas e comandas; reconstrução da receita bruta",
            "nature": "variable",
        }
    )
    for qs, label in [(items, "CMV das vendas"), (commands, "CMV das comandas")]:
        value = (
            qs.aggregate(
                v=Sum(
                    ExpressionWrapper(
                        F("quantity") * F("cost_snapshot"), output_field=DecimalField()
                    )
                )
            )["v"]
            or ZERO
        )
        amounts["direct_costs"] += value
        details.append(
            {
                "label": label,
                "line": "direct_costs",
                "amount": value,
                "source": "Custo registrado na venda",
                "nature": "variable",
            }
        )
    value = materials.aggregate(v=Sum("cost_snapshot"))["v"] or ZERO
    amounts["direct_costs"] += value
    details.append(
        {
            "label": "Insumos consumidos",
            "line": "direct_costs",
            "amount": value,
            "source": "Registros de consumo",
            "nature": "variable",
        }
    )
    commissions = ProfessionalCommission.objects.filter(
        tenant=tenant, status__in=["pending", "paid"]
    ).filter(
        Q(calculation__earned_on__range=[start, end])
        | Q(calculation__isnull=True, created_at__gte=first, created_at__lt=after)
    )
    if unit:
        commissions = commissions.filter(professional__unit=unit)
    value = commissions.aggregate(v=Sum("commission_amount"))["v"] or ZERO
    amounts["direct_costs"] += value
    details.append(
        {
            "label": "Comissões reconhecidas (pagas e pendentes)",
            "line": "direct_costs",
            "amount": value,
            "source": "Sem duplicar o pagamento no financeiro",
            "nature": "variable",
        }
    )
    # Fees are sourced from verified provider transactions; allocation follows the booked unit.
    from billing.models import TenantPaymentTransaction

    fees = TenantPaymentTransaction.objects.filter(
        tenant=tenant, status="paid", paid_at__gte=first, paid_at__lt=after
    )
    if unit:
        from scheduling.models import Appointment

        fees = fees.filter(
            reference_type="appointment",
            reference_id__in=Appointment.objects.filter(
                tenant=tenant, unit=unit
            ).values("pk"),
        )
    value = fees.aggregate(v=Sum("fee_amount"))["v"] or ZERO
    amounts["financial_expenses"] += value
    details.append(
        {
            "label": "Taxas do provedor de pagamento",
            "line": "financial_expenses",
            "amount": value,
            "source": "Transações conciliadas",
            "nature": "variable",
        }
    )
    net = amounts["gross_revenue"] - amounts["deductions"]
    gross = net - amounts["direct_costs"]
    operating = gross - amounts["operating_expenses"]
    before_tax = operating + amounts["financial_income"] - amounts["financial_expenses"]
    result = before_tax - amounts["income_tax"]
    undated = FinancialTransaction.objects.filter(
        tenant=tenant, competence_at__isnull=True
    ).exclude(status="cancelled")
    if unit:
        undated = undated.filter(unit=unit)
    if undated.exists():
        warnings.append(
            "Há lançamentos sem data de competência; eles não entram no período."
        )
    sections = [{"key": k, "label": label, "amount": amounts[k]} for k, label in LINES]
    subtotals = [
        ("Receita líquida", net),
        ("Lucro bruto", gross),
        ("Resultado operacional", operating),
        ("Resultado antes dos tributos", before_tax),
        ("Resultado líquido", result),
    ]
    return {
        "sections": sections,
        "subtotals": [{"label": l, "amount": v} for l, v in subtotals],
        "details": details,
        "warnings": list(dict.fromkeys(warnings)),
        "result": result,
        "margin": (result / net * 100).quantize(Decimal(".01")) if net else None,
    }


def cash_flow(tenant, start, end, unit=None):
    from .models import GiftCardEntry
    from barber.models import BarberCommandPayment
    from billing.models import TenantPaymentTransaction
    from scheduling.models import Appointment

    tz = ZoneInfo(tenant.timezone or "America/Recife")
    first = datetime.combine(start, time.min, tz)
    after = datetime.combine(end + timedelta(days=1), time.min, tz)
    rows = FinancialTransaction.objects.filter(
        tenant=tenant, status="paid", paid_at__gte=first, paid_at__lt=after
    ).exclude(source_type="barber_command")
    if unit:
        rows = rows.filter(unit=unit)
    income = expense = ZERO
    for row in rows:
        amount = row.amount
        if row.type == "income" and row.appointment_id:
            prepaid = (
                TenantPaymentTransaction.objects.filter(
                    tenant=tenant,
                    reference_type="appointment",
                    reference_id=row.appointment_id,
                    status="paid",
                ).aggregate(v=Sum("gross_amount"))["v"]
                or ZERO
            )
            amount = max(amount - prepaid, ZERO)
        if row.type == "income":
            income += amount
        else:
            expense += amount
    receipts = BarberCommandPayment.objects.filter(
        tenant=tenant,
        voided_at__isnull=True,
        received_at__gte=first,
        received_at__lt=after,
    ).exclude(method__in=["gift_card","prepaid_card"])
    prepayments = TenantPaymentTransaction.objects.filter(
        tenant=tenant,
        reference_type="appointment",
        status="paid",
        paid_at__gte=first,
        paid_at__lt=after,
    )
    gifts = GiftCardEntry.objects.filter(
        tenant=tenant, kind="issue", created_at__gte=first, created_at__lt=after
    )
    if unit:
        receipts = receipts.filter(
            Q(command__appointment__unit=unit)
            | Q(command__appointment__isnull=True, command__professional__unit=unit)
        )
        prepayments = prepayments.filter(
            reference_id__in=Appointment.objects.filter(
                tenant=tenant, unit=unit
            ).values("pk")
        )
        gifts = gifts.filter(card__unit=unit)
    income += receipts.aggregate(v=Sum("amount"))["v"] or ZERO
    income += prepayments.aggregate(v=Sum("gross_amount"))["v"] or ZERO
    prepaid_fees = prepayments.aggregate(v=Sum("fee_amount"))["v"] or ZERO
    expense += prepaid_fees
    gift_receipts = gifts.aggregate(v=Sum("amount"))["v"] or ZERO
    income += gift_receipts
    return {
        "income": income,
        "expense": expense,
        "net": income - expense,
        "gift_receipts": gift_receipts,
        "prepaid_fees": prepaid_fees,
    }
