"""Daily cash sheet ("folha do caixa"): one line per patient with the professional,
amount split (dentista / consultório / outros) and payment method, linked to the
company ledger. A closed sheet is locked; changes require a manager's
authorization and every change is audited."""
import uuid
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from core.audit import append_audit
from core.unit_scope import selected_unit
from scheduling.models import Customer, Professional
from .clinic_models import (ClinicCashCorrection, ClinicCashEntry, ClinicExpense, ClinicPaymentMethod,
                            ClinicReceipt, ClinicCashClosing, ClinicCashWithdrawal)
from .clinic_services import access, lock_company, money
from .models import CashSession, FinancialTransaction

MANAGERS = {"owner", "tenant-admin", "manager"}
WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
KIND_LABEL = {"cash": "Dinheiro", "pix": "Pix", "card": "Débito/Crédito"}


def is_manager(user):
    return user.role in MANAGERS


def active_correction(session):
    return session.clinical_corrections.filter(status=ClinicCashCorrection.Status.APPROVED).first()


TEAM = {"owner", "tenant-admin", "manager", "reception", "finance"}


def can_edit(session, user):
    """Any day's sheet stays editable by management; the front desk only if the manager allowed it. Audited."""
    from .reception_permissions import allowed
    if session.deleted_at:
        return False
    if user.role == "reception" and (session.status != CashSession.Status.OPEN or _earlier_day(session)):
        return allowed(user, "dias_anteriores")
    if session.status == CashSession.Status.OPEN or user.role in TEAM:
        return True
    correction = active_correction(session)
    return bool(correction and (is_manager(user) or correction.requested_by_id == user.pk))


def _is_today_open(session, tenant):
    from .clinic_services import business_today, session_day
    return session.status == CashSession.Status.OPEN and session_day(session) == business_today(tenant)


def _earlier_day(session):
    from .clinic_services import business_today, session_day
    return session_day(session) < business_today(session.tenant)


def _entry_time(session):
    from .clinic_services import business_today, session_day, _zone
    from datetime import datetime, time
    day = session_day(session)
    if session.status == CashSession.Status.CLOSED and session.closed_at:
        return session.closed_at
    if day < business_today(session.tenant):
        return timezone.make_aware(datetime.combine(day, time(12, 0)), _zone(session.tenant))
    return timezone.now()


def refresh_closed(session, user):
    """A closed sheet edited later gets its conference recalculated (and audited by the caller)."""
    if session.status != CashSession.Status.CLOSED:
        return
    before = {"expected": str(session.expected_amount), "difference": str(session.difference_amount)}
    session.expected_amount = expected_cash(session)
    session.difference_amount = (session.closing_amount or Decimal(0)) - session.expected_amount
    session.save(update_fields=["expected_amount", "difference_amount"])
    closing = ClinicCashClosing.objects.filter(session=session).first()
    if closing:
        summary = dict(closing.summary or {})
        data = report(session)
        summary.update({"cash_expected": str(session.expected_amount), "difference": str(session.difference_amount),
                        "expenses": format(data["expenses_total"], ".2f"), "withdrawals": format(data["withdrawals_total"], ".2f"),
                        "net": format(data["columns"]["total"] - data["expenses_total"], ".2f"),
                        "edited_after_close": summary.get("edited_after_close", 0) + 1,
                        "professionals": [{k: (format(v, ".2f") if isinstance(v, Decimal) else v) for k, v in r.items()}
                                          for r in by_professional(session)]})
        ClinicCashClosing.objects.filter(pk=closing.pk).update(summary=summary)
    append_audit(tenant=session.tenant, user=user, action="clinic.cash_report.recalculated", entity_type="CashSession",
                 entity_id=session.pk, before=before,
                 after={"expected": str(session.expected_amount), "difference": str(session.difference_amount)})


def _lock_session(tenant, session_id):
    return CashSession.objects.select_for_update().get(pk=session_id, tenant=tenant)


def _professional_label(professional, manual):
    if professional:
        return professional.name
    name = " ".join((manual or "").split())
    if not 3 <= len(name) <= 120:
        raise ValidationError("Selecione o profissional ou digite o nome de quem atendeu.")
    return name


def _amounts(dentist, clinic, other):
    values = [money(v or 0, allow_zero=True) for v in (dentist, clinic, other)]
    # R$ 0 is valid: evaluations and repairs at no charge are still recorded on the day's sheet.
    return values, sum(values, Decimal("0"))


@transaction.atomic
def add_entry(*, user, session_id, customer, professional, professional_name, dentist_amount, clinic_amount,
              other_amount, method, notes, request_id, receivable=None):
    """One line on a cash sheet. `receivable` is a pending treatment-plan income that this line pays: the line
    reuses that transaction instead of creating another one, so the money is counted once."""
    tenant = lock_company(user)
    existing = ClinicCashEntry.objects.filter(request_id=request_id).first()
    if existing:
        if existing.session.tenant_id != tenant.pk or existing.created_by_id != user.pk or existing.customer_id != customer.pk:
            raise ValidationError("Este lançamento já foi registrado com outros dados. Atualize a página.")
        return existing
    from .reception_permissions import require
    require(user, "caixa")
    session = _lock_session(tenant, session_id)
    if not can_edit(session, user):
        raise PermissionDenied("Este caixa é de outro dia ou já foi fechado, e o gestor não liberou correções para a recepção.")
    if customer.tenant_id != tenant.pk or not customer.active:
        raise PermissionDenied
    if professional and professional.tenant_id != tenant.pk:
        raise PermissionDenied
    if method and (method.tenant_id != tenant.pk or not method.active):
        raise PermissionDenied
    label = _professional_label(professional, professional_name)
    (dentist, clinic, other), total = _amounts(dentist_amount, clinic_amount, other_amount)
    number = (session.clinical_entries.aggregate(v=Max("number"))["v"] or 0) + 1
    now = _entry_time(session)
    from .clinic_services import session_day
    day = session_day(session)
    if receivable is not None:
        tx = FinancialTransaction.objects.select_for_update().get(pk=receivable.pk, tenant=tenant, type="income")
        if tx.status != "pending" or ClinicCashEntry.objects.filter(transaction=tx).exists():
            raise ValidationError("Este recebível já foi baixado. Atualize a página.")
        if total != tx.amount:
            raise ValidationError("O valor lançado precisa ser igual ao valor do recebível.")
        if not method:
            raise ValidationError("Escolha a forma de pagamento.")
        tx.unit, tx.status, tx.paid_at, tx.payment_method = session.unit, "paid", now, method.kind
        tx.save(update_fields=["unit", "status", "paid_at", "payment_method", "updated_at"])
    else:
        tx = None
    tx = tx or FinancialTransaction.objects.create(
        tenant=tenant, unit=session.unit, type="income", source_type="clinic-cash-entry",
        status="paid" if method else "pending", paid_at=now if method else None,
        payment_method=method.kind if method else "", amount=total,
        description=f"Caixa {day:%d/%m/%Y} · {label} · {customer.name}"[:190],
        competence_at=day,
        due_at=None if method else day,
        idempotency_key=f"clinic-cash-entry:{request_id}",
    )
    row = ClinicCashEntry.objects.create(
        session=session, number=number, customer=customer, professional=professional, professional_name=label,
        dentist_amount=dentist, clinic_amount=clinic, other_amount=other, total=total, method=method,
        method_name=method.name if method else "", status="paid" if method else "open", notes=(notes or "")[:300],
        transaction=tx, created_by=user, request_id=request_id,
    )
    if receivable is None:
        tx.source_id = row.pk
        tx.save(update_fields=["source_id", "updated_at"])
    append_audit(tenant=tenant, user=user, action="clinic.cash_entry.created", entity_type="ClinicCashEntry", entity_id=row.pk,
                 after={"session": session.pk, "total": str(total), "method": method.kind if method else "open",
                        "late": session.status != CashSession.Status.OPEN})
    refresh_closed(session, user)
    return row


def _snapshot(row):
    return {"customer": row.customer_id, "professional": row.professional_name, "dentist": str(row.dentist_amount),
            "clinic": str(row.clinic_amount), "other": str(row.other_amount), "total": str(row.total),
            "method": row.method_name or "em aberto", "status": row.status}


@transaction.atomic
def update_entry(*, user, entry_id, customer, professional, professional_name, dentist_amount, clinic_amount,
                 other_amount, method, notes):
    tenant = lock_company(user)
    row = ClinicCashEntry.objects.select_for_update().select_related("session", "transaction").get(pk=entry_id, session__tenant=tenant)
    session = _lock_session(tenant, row.session_id)
    if not can_edit(session, user):
        raise PermissionDenied("Caixa fechado. Peça autorização do gestor para corrigir o relatório.")
    if row.created_by_id != user.pk and not is_manager(user) and user.role not in TEAM:
        raise PermissionDenied("Somente quem lançou, a recepção ou a gestão pode alterar esta linha.")
    if row.status == ClinicCashEntry.Status.CANCELLED:
        raise ValidationError("Linha cancelada não pode ser alterada.")
    if customer.tenant_id != tenant.pk or (professional and professional.tenant_id != tenant.pk) or (method and method.tenant_id != tenant.pk):
        raise PermissionDenied
    before = _snapshot(row)
    (dentist, clinic, other), total = _amounts(dentist_amount, clinic_amount, other_amount)
    row.customer, row.professional = customer, professional
    row.professional_name = _professional_label(professional, professional_name)
    row.dentist_amount, row.clinic_amount, row.other_amount, row.total = dentist, clinic, other, total
    row.method, row.method_name = method, method.name if method else ""
    row.status = "paid" if method else "open"
    row.notes = (notes or "")[:300]
    row.save()
    tx = FinancialTransaction.objects.select_for_update().get(pk=row.transaction_id, tenant=tenant)
    tx.amount = total
    tx.payment_method = method.kind if method else ""
    tx.status = "paid" if method else "pending"
    tx.paid_at = (tx.paid_at or _entry_time(session)) if method else None
    from .clinic_services import session_day
    tx.due_at = None if method else session_day(session)
    tx.save(update_fields=["amount", "payment_method", "status", "paid_at", "due_at", "updated_at"])
    append_audit(tenant=tenant, user=user, action="clinic.cash_entry.updated", entity_type="ClinicCashEntry", entity_id=row.pk,
                 before=before, after=_snapshot(row))
    refresh_closed(session, user)
    return row


def reopen_receivable(tx):
    """A cancelled line that paid a treatment-plan receivable gives the patient's debt back as a new pending row."""
    if tx.source_type != "clinical-plan":
        return None
    return FinancialTransaction.objects.create(
        tenant_id=tx.tenant_id, unit_id=tx.unit_id, type="income", status="pending", source_type="clinical-plan",
        source_id=tx.source_id, description=tx.description, amount=tx.amount, competence_at=tx.competence_at,
        due_at=tx.due_at, idempotency_key=f"clinical-plan-reopen:{tx.pk}"[:100])


@transaction.atomic
def cancel_entry(*, user, entry_id, reason, approved_removal=False):
    from .reception_permissions import allowed
    if not approved_removal and not allowed(user, "apagar_lancamento"):
        raise PermissionDenied("Para apagar este lançamento, peça ao gestor: use “Pedir para apagar”.")
    tenant = lock_company(user)
    row = ClinicCashEntry.objects.select_for_update().get(pk=entry_id, session__tenant=tenant)
    session = _lock_session(tenant, row.session_id)
    if not can_edit(session, user):
        raise PermissionDenied("Caixa fechado. Peça autorização do gestor para corrigir o relatório.")
    if row.created_by_id != user.pk and not is_manager(user) and user.role not in TEAM:
        raise PermissionDenied("Somente quem lançou, a recepção ou a gestão pode cancelar esta linha.")
    reason = " ".join((reason or "").split())
    if not 3 <= len(reason) <= 300:
        raise ValidationError("Informe o motivo do cancelamento.")
    before = _snapshot(row)
    row.status = ClinicCashEntry.Status.CANCELLED
    row.notes = f"Cancelado: {reason}"[:300]
    row.save(update_fields=["status", "notes", "updated_at"])
    tx = FinancialTransaction.objects.select_for_update().get(pk=row.transaction_id, tenant=tenant)
    tx.status = "cancelled"
    tx.save(update_fields=["status", "updated_at"])
    reopen_receivable(tx)
    append_audit(tenant=tenant, user=user, action="clinic.cash_entry.cancelled", entity_type="ClinicCashEntry", entity_id=row.pk,
                 before=before, after={"status": "cancelled", "reason": reason})
    refresh_closed(session, user)
    return row


@transaction.atomic
def request_correction(*, user, session_id, reason):
    tenant = lock_company(user)
    session = _lock_session(tenant, session_id)
    if session.status != CashSession.Status.CLOSED:
        raise ValidationError("O caixa ainda está aberto; ajuste as linhas diretamente.")
    if session.clinical_corrections.filter(status__in=["requested", "approved"]).exists():
        raise ValidationError("Já existe uma correção pendente ou liberada para este caixa.")
    reason = " ".join((reason or "").split())
    if not 5 <= len(reason) <= 500:
        raise ValidationError("Explique o que precisa ser corrigido.")
    manager = is_manager(user)
    row = ClinicCashCorrection.objects.create(
        session=session, requested_by=user, reason=reason,
        status="approved" if manager else "requested",
        decided_by=user if manager else None, decided_at=timezone.now() if manager else None,
        decision_note="Aberta pela gestão." if manager else "",
    )
    append_audit(tenant=tenant, user=user, action="clinic.cash_report.correction_requested", entity_type="CashSession",
                 entity_id=session.pk, after={"correction": row.pk, "status": row.status, "reason": reason})
    return row


@transaction.atomic
def decide_correction(*, user, correction_id, approve, note=""):
    tenant = lock_company(user)
    if not is_manager(user):
        raise PermissionDenied("Somente o gestor autoriza correções no caixa fechado.")
    row = ClinicCashCorrection.objects.select_for_update().get(pk=correction_id, session__tenant=tenant)
    if row.status != ClinicCashCorrection.Status.REQUESTED:
        raise ValidationError("Esta solicitação já foi decidida.")
    row.status = "approved" if approve else "rejected"
    row.decided_by, row.decided_at, row.decision_note = user, timezone.now(), (note or "")[:500]
    row.save()
    append_audit(tenant=tenant, user=user, action="clinic.cash_report.correction_" + row.status, entity_type="CashSession",
                 entity_id=row.session_id, after={"correction": row.pk, "note": row.decision_note})
    return row


def expected_cash(session):
    """Cash drawer for this sheet: opening + cash received - cash expenses - withdrawals (sangria)."""
    entries = session.clinical_entries.filter(status="paid", method__kind="cash").aggregate(v=Sum("total"))["v"] or Decimal(0)
    receipts = ClinicReceipt.objects.filter(session=session, method__kind="cash").aggregate(v=Sum("amount"))["v"] or Decimal(0)
    spent = ClinicExpense.objects.filter(session=session, method__kind="cash").exclude(transaction__status="cancelled").aggregate(
        v=Sum("transaction__amount"))["v"] or Decimal(0)
    # Retiradas (sangria) leave the drawer too, but are not expenses.
    spent += ClinicCashWithdrawal.objects.filter(session=session, cancelled_at__isnull=True).aggregate(
        v=Sum("amount"))["v"] or Decimal(0)
    legacy = Decimal(0)
    if not session.professional_id:
        # Treatment-plan receivables paid in cash at the desk are not linked to a sheet line.
        legacy = FinancialTransaction.objects.filter(
            tenant=session.tenant, unit=session.unit, status="paid", payment_method__in=["cash", "dinheiro"],
            source_type="clinical-plan", clinic_cash_entry__isnull=True, paid_at__gte=session.opened_at,
            paid_at__lte=session.closed_at or timezone.now()).aggregate(v=Sum("amount"))["v"] or Decimal(0)
    return session.opening_amount + entries + receipts - spent + legacy


@transaction.atomic
def finish_correction(*, user, correction_id):
    tenant = lock_company(user)
    row = ClinicCashCorrection.objects.select_for_update().get(pk=correction_id, session__tenant=tenant)
    if row.status != ClinicCashCorrection.Status.APPROVED or not (is_manager(user) or row.requested_by_id == user.pk):
        raise PermissionDenied
    session = _lock_session(tenant, row.session_id)
    before = {"expected": str(session.expected_amount), "difference": str(session.difference_amount)}
    session.expected_amount = expected_cash(session)
    session.difference_amount = (session.closing_amount or Decimal(0)) - session.expected_amount
    session.save(update_fields=["expected_amount", "difference_amount"])
    closing = ClinicCashClosing.objects.filter(session=session).first()
    if closing:
        summary = dict(closing.summary or {})
        summary.update({"cash_expected": str(session.expected_amount), "difference": str(session.difference_amount),
                        "corrections": summary.get("corrections", 0) + 1})
        ClinicCashClosing.objects.filter(pk=closing.pk).update(summary=summary)
    row.status, row.finished_at = ClinicCashCorrection.Status.DONE, timezone.now()
    row.save(update_fields=["status", "finished_at"])
    append_audit(tenant=tenant, user=user, action="clinic.cash_report.correction_finished", entity_type="CashSession",
                 entity_id=session.pk, before=before,
                 after={"expected": str(session.expected_amount), "difference": str(session.difference_amount), "correction": row.pk})
    return row


def by_professional(session):
    """Fechamento do dia por profissional: o que cada dentista recebeu neste caixa (parte dele e da clínica)
    e as despesas marcadas para ele."""
    rows = {}

    def line(name):
        return rows.setdefault(name or "Sem profissional informado", {
            "professional": name or "Sem profissional informado", "patients": 0, "dentist": Decimal(0),
            "clinic": Decimal(0), "other": Decimal(0), "total": Decimal(0), "open": Decimal(0),
            "expenses": Decimal(0)})

    for row in session.clinical_entries.exclude(status="cancelled"):
        item = line(row.professional_name)
        item["patients"] += 1
        if row.status == "open":
            item["open"] += row.total
            continue
        item["dentist"] += row.dentist_amount
        item["clinic"] += row.clinic_amount
        item["other"] += row.other_amount
        item["total"] += row.total
    for receipt in ClinicReceipt.objects.filter(session=session).select_related("installment__charge__professional"):
        professional = receipt.installment.charge.professional
        item = line(professional.name if professional else "")
        item["patients"] += 1
        item["total"] += receipt.amount
    for expense in (ClinicExpense.objects.filter(session=session, professional__isnull=False)
                    .exclude(transaction__status="cancelled").select_related("professional", "transaction")):
        line(expense.professional.name)["expenses"] += expense.transaction.amount
    for item in rows.values():
        item["dentist_net"] = item["dentist"] - item["expenses"]
    return sorted(rows.values(), key=lambda r: (-r["total"], r["professional"]))


def report(session):
    from .clinic_services import opened_before_today
    entries = list(session.clinical_entries.select_related("customer", "method").order_by("number"))
    receipts = list(ClinicReceipt.objects.filter(session=session).select_related(
        "installment__charge__customer", "installment__charge__professional", "method").order_by("created_at", "pk"))
    by_kind = {"cash": Decimal(0), "pix": Decimal(0), "card": Decimal(0)}
    columns = {"dentist": Decimal(0), "clinic": Decimal(0), "other": Decimal(0), "total": Decimal(0)}
    open_rows = []
    for row in entries:
        if row.status == "cancelled":
            continue
        if row.status == "open":
            open_rows.append(row)
            continue
        columns["dentist"] += row.dentist_amount
        columns["clinic"] += row.clinic_amount
        columns["other"] += row.other_amount
        columns["total"] += row.total
        by_kind[row.method.kind] = by_kind.get(row.method.kind, Decimal(0)) + row.total
    for receipt in receipts:
        columns["total"] += receipt.amount
        by_kind[receipt.method.kind] = by_kind.get(receipt.method.kind, Decimal(0)) + receipt.amount
    expenses = list(ClinicExpense.objects.filter(session=session).exclude(transaction__status="cancelled")
                    .select_related("transaction", "recorded_by", "method", "professional").order_by("created_at", "pk"))
    withdrawals = list(ClinicCashWithdrawal.objects.filter(session=session, cancelled_at__isnull=True)
                       .select_related("recorded_by", "converted_from__transaction").order_by("occurred_at", "pk"))
    opened = timezone.localtime(session.opened_at)
    return {
        "session": session, "entries": entries, "receipts": receipts, "columns": columns,
        "kinds": [(KIND_LABEL[k], by_kind.get(k, Decimal(0))) for k in ("cash", "pix", "card")],
        "kinds_total": sum(by_kind.values(), Decimal(0)),
        "open_rows": open_rows, "open_total": sum((r.total for r in open_rows), Decimal(0)),
        "expenses": expenses,
        "withdrawals": withdrawals,
        "withdrawals_total": sum((w.amount for w in withdrawals), Decimal(0)),
        "expenses_total": sum((e.transaction.amount for e in expenses), Decimal(0)),
        "expenses_cash": sum((e.transaction.amount for e in expenses if e.method and e.method.kind == "cash"), Decimal(0)),
        "net_total": columns["total"] - sum((e.transaction.amount for e in expenses), Decimal(0)),
        "drawer_expected": expected_cash(session),
        "date": opened.date(), "weekday": WEEKDAYS[opened.weekday()],
        "professionals": by_professional(session), "previous_day_open": opened_before_today(session),
        "locked": session.status == CashSession.Status.CLOSED and not active_correction(session),
        "correction": active_correction(session),
        "pending_correction": session.clinical_corrections.filter(status="requested").first(),
        "corrections": session.clinical_corrections.select_related("requested_by", "decided_by")[:20],
    }


class EntryForm(forms.Form):
    request_id = forms.UUIDField(widget=forms.HiddenInput)
    entry_id = forms.IntegerField(widget=forms.HiddenInput, required=False)
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), label="Paciente")
    professional = forms.ModelChoiceField(queryset=Professional.objects.none(), label="Dentista / profissional", required=False,
                                          empty_label="Não está na lista (digitar abaixo)")
    professional_name = forms.CharField(label="Profissional não cadastrado (nome)", max_length=120, required=False)
    dentist_amount = forms.DecimalField(label="Dentista (R$)", max_digits=12, decimal_places=2, min_value=0, initial=0, required=False)
    clinic_amount = forms.DecimalField(label="Consultório (R$)", max_digits=12, decimal_places=2, min_value=0, initial=0, required=False)
    other_amount = forms.DecimalField(label="Outros (R$)", max_digits=12, decimal_places=2, min_value=0, initial=0, required=False)
    method = forms.ModelChoiceField(queryset=ClinicPaymentMethod.objects.none(), label="Forma de pagamento", required=False,
                                    empty_label="Em aberto (ainda não pago)")
    notes = forms.CharField(label="Observação da linha (opcional)", max_length=300, required=False)

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(tenant=tenant, active=True).order_by("name")
        self.fields["professional"].queryset = Professional.objects.filter(tenant=tenant, active=True).order_by("name")
        self.fields["method"].queryset = ClinicPaymentMethod.objects.filter(tenant=tenant, active=True).order_by("kind", "name")
        split_fields(self, tenant=tenant)

    def clean(self):
        data = super().clean()
        if not data.get("professional") and not (data.get("professional_name") or "").strip():
            self.add_error("professional_name", "Selecione o profissional ou digite o nome de quem atendeu.")
        if not data.get("entry_id"):
            clean_split(self, data)
        return data


def split_fields(form, *, tenant):
    """Optional second payment method for a mixed payment (e.g. part cash, part Pix)."""
    form.fields["second_method"] = forms.ModelChoiceField(
        queryset=ClinicPaymentMethod.objects.filter(tenant=tenant, active=True).order_by("kind", "name"),
        label="Segunda forma (opcional)", required=False, empty_label="Só uma forma de pagamento")
    form.fields["second_amount"] = forms.DecimalField(label="Valor pago na segunda forma (R$)", max_digits=12, decimal_places=2,
                                                      min_value=Decimal("0.01"), required=False)


def clean_split(form, data):
    second, value = data.get("second_method"), data.get("second_amount")
    if not second and not value:
        return
    total = sum((data.get(k) or Decimal(0) for k in ("dentist_amount", "clinic_amount", "other_amount")), Decimal(0))
    if not second:
        form.add_error("second_method", "Escolha a segunda forma de pagamento.")
    elif not value:
        form.add_error("second_amount", "Informe quanto foi pago na segunda forma.")
    elif not data.get("method"):
        form.add_error("method", "Escolha a primeira forma de pagamento.")
    elif second == data.get("method"):
        form.add_error("second_method", "A segunda forma precisa ser diferente da primeira.")
    elif value >= total:
        form.add_error("second_amount", "O valor da segunda forma precisa ser menor que o total do atendimento.")


def _part(value, ratio):
    return (value * ratio).quantize(Decimal("0.01"))


@transaction.atomic
def add_split_entry(*, user, session_id, second_method=None, second_amount=None, **data):
    """One payment in two methods becomes two lines of the same sheet. The dentist/clinic/other split is kept
    in the same proportion in both lines; both lines note the whole payment."""
    if not second_method or not second_amount:
        return [add_entry(user=user, session_id=session_id, **data)]
    keys = ("dentist_amount", "clinic_amount", "other_amount")
    amounts = {k: money(data.get(k) or 0, allow_zero=True) for k in keys}
    total = sum(amounts.values(), Decimal(0))
    second_amount = money(second_amount)
    if second_amount <= 0 or second_amount >= total:
        raise ValidationError("O valor da segunda forma precisa ser maior que zero e menor que o total.")
    ratio = second_amount / total
    second = {k: _part(v, ratio) for k, v in amounts.items()}
    biggest = max(keys, key=lambda k: amounts[k])
    second[biggest] += second_amount - sum(second.values(), Decimal(0))  # rounding goes to the largest column
    first = {k: amounts[k] - second[k] for k in keys}
    first_method = data["method"]
    note = (f"Pago em 2 formas: {first_method.name} R$ {total - second_amount:.2f} + {second_method.name} R$ {second_amount:.2f}"
            .replace(".", ","))
    notes = (f"{data.get('notes') or ''} · {note}" if data.get("notes") else note)[:300]
    request_id = data["request_id"]
    one = add_entry(user=user, session_id=session_id, **{**data, **first, "notes": notes})
    two = add_entry(user=user, session_id=session_id, **{**data, **second, "notes": notes, "method": second_method,
                                                          "request_id": uuid.uuid5(request_id, "segunda-forma")})
    return [one, two]


CLOSED_CONFIRMATION = ("Este caixa já foi fechado. Marque a confirmação para lançar ou alterar nele: "
                       "a conferência é recalculada e a alteração fica na auditoria.")


def _require_closed_confirmation(request, session):
    """Changing a closed sheet is allowed (audited), but never by accident."""
    if session.status == CashSession.Status.CLOSED and request.POST.get("confirm_closed") != "1":
        raise ValidationError(CLOSED_CONFIRMATION)


def _payload(form):
    data = dict(form.cleaned_data)
    data.pop("entry_id", None)
    return data


def _entry_payload(form):
    data = _payload(form)
    data.pop("second_method", None)
    data.pop("second_amount", None)
    return data


@login_required
@never_cache
def cash_sheet(request, pk=None):
    tenant = access(request.user)
    unit = selected_unit(request, tenant)
    sessions = CashSession.objects.filter(tenant=tenant, deleted_at__isnull=True)
    if not is_manager(request.user):
        sessions = sessions.filter(unit=unit)
    if pk:
        session = get_object_or_404(sessions.select_related("professional", "tenant"), pk=pk)
    else:
        from .clinic_services import business_today
        today = sessions.filter(unit=unit, business_date=business_today(tenant))
        session = today.filter(status="open").order_by("professional_id").first() or today.first() \
            or sessions.filter(unit=unit).order_by("-opened_at").first()
        if not session:
            messages.info(request, "Os caixas do dia são criados no primeiro recebimento, ou abra um no Financeiro.")
            return redirect("clinic-finance-desk")
        return redirect("clinic-cash-sheet-detail", pk=session.pk)
    action = request.POST.get("action") if request.method == "POST" else ""
    editing = None
    if request.GET.get("editar", "").isdigit():
        editing = session.clinical_entries.filter(pk=int(request.GET["editar"])).exclude(status="cancelled").first()
    initial = {"request_id": uuid.uuid4(), "professional": session.professional_id}
    if editing:
        initial.update(entry_id=editing.pk, customer=editing.customer_id, professional=editing.professional_id,
                       professional_name="" if editing.professional_id else editing.professional_name,
                       dentist_amount=editing.dentist_amount, clinic_amount=editing.clinic_amount,
                       other_amount=editing.other_amount, method=editing.method_id, notes=editing.notes)
    form = EntryForm(request.POST if action in {"add", "update"} else None, tenant=tenant, initial=initial)
    if request.method == "POST":
        try:
            if action == "add" and form.is_valid():
                # Um caixa só por dia: a linha fica nesta folha, ligada ao profissional escolhido.
                target = session
                _require_closed_confirmation(request, target)
                add_split_entry(user=request.user, session_id=target.pk, **_payload(form))
            elif action == "update" and form.is_valid() and form.cleaned_data.get("entry_id"):
                _require_closed_confirmation(request, session)
                payload = _entry_payload(form)
                payload.pop("request_id")
                update_entry(user=request.user, entry_id=form.cleaned_data["entry_id"], **payload)
            elif action == "cancel" and request.POST.get("entry", "").isdigit():
                cancel_entry(user=request.user, entry_id=int(request.POST["entry"]), reason=request.POST.get("reason", ""))
            elif action == "request-removal" and request.POST.get("entry", "").isdigit():
                request_removal(user=request.user, entry_id=int(request.POST["entry"]), reason=request.POST.get("reason", ""))
                messages.success(request, "Pedido enviado ao gestor. O lançamento continua no caixa até a aprovação.")
                return redirect(reverse("clinic-cash-sheet-detail", args=[session.pk]))
            elif action in {"approve-removal", "reject-removal"} and request.POST.get("removal", "").isdigit():
                decide_removal(user=request.user, removal_id=int(request.POST["removal"]),
                               approve=action == "approve-removal", note=request.POST.get("note", ""))
            elif action == "delete-sheet":
                delete_sheet(user=request.user, session_id=session.pk, reason=request.POST.get("reason", ""))
                messages.success(request, "Caixa apagado. Os lançamentos foram cancelados e tudo ficou registrado na auditoria.")
                return redirect("clinic-cash-days")
            elif action == "convert-expense" and request.POST.get("expense", "").isdigit():
                if not ClinicExpense.objects.filter(pk=int(request.POST["expense"]), session=session).exists():
                    raise PermissionDenied
                convert_expense(user=request.user, expense_id=int(request.POST["expense"]), reason=request.POST.get("reason", ""))
                messages.success(request, "Despesa convertida em retirada de caixa. A gaveta esperada não mudou.")
                return redirect(reverse("clinic-cash-sheet-detail", args=[session.pk]))
            elif action == "cancel-withdrawal" and request.POST.get("withdrawal", "").isdigit():
                if not ClinicCashWithdrawal.objects.filter(pk=int(request.POST["withdrawal"]), session=session).exists():
                    raise PermissionDenied
                cancel_withdrawal(user=request.user, withdrawal_id=int(request.POST["withdrawal"]), reason=request.POST.get("reason", ""))
            elif action == "request-correction":
                request_correction(user=request.user, session_id=session.pk, reason=request.POST.get("reason", ""))
            elif action in {"approve", "reject"} and request.POST.get("correction", "").isdigit():
                decide_correction(user=request.user, correction_id=int(request.POST["correction"]),
                                  approve=action == "approve", note=request.POST.get("note", ""))
            elif action == "finish" and request.POST.get("correction", "").isdigit():
                finish_correction(user=request.user, correction_id=int(request.POST["correction"]))
            elif action not in {"add", "update"}:
                raise PermissionDenied
            else:
                raise ValidationError("Revise os campos indicados.")
            messages.success(request, "Caixa atualizado.")
            return redirect(reverse("clinic-cash-sheet-detail", args=[session.pk]))
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        except ClinicCashEntry.DoesNotExist:
            raise PermissionDenied from None
    context = report(session)
    from .clinic_services import session_day
    context["day_sheets"] = sessions.filter(unit=session.unit, business_date=session_day(session)).select_related("professional").order_by("professional__name")
    from .clinic_models import ClinicCashEntryRemoval
    from .reception_permissions import allowed, is_manager as gestor
    removals = ClinicCashEntryRemoval.objects.filter(entry__session=session).select_related("entry", "requested_by")
    pending = {r.entry_id: r for r in removals if r.status == ClinicCashEntryRemoval.Status.REQUESTED}
    for row in context.get("entries", []):
        row.pending_removal = pending.get(row.pk)
    context.update({
        "form": form, "editing": editing, "can_edit": can_edit(session, request.user),
        "manager": is_manager(request.user), "gestor": gestor(request.user),
        "can_delete_line": allowed(request.user, "apagar_lancamento"), "pending_removals": list(pending.values()),
        "history": sessions.filter(unit=session.unit).order_by("-opened_at")[:15],
        # A despesa pode ser lançada no dia desta folha (hoje ou anterior, conforme a permissão da recepção).
        "can_expense": can_edit(session, request.user) and allowed(request.user, "despesas")
        and (_is_today_open(session, tenant) or allowed(request.user, "dias_anteriores")),
        "sheet_day": session_day(session),
        "can_cancel_withdrawal": (gestor(request.user) and bool(context.get("correction"))) if session.status == CashSession.Status.CLOSED
        else True,
        "me": request.user.pk,
    })
    return render(request, "finance/clinic_cash_sheet.html", context)


@transaction.atomic
def request_removal(*, user, entry_id, reason):
    from .clinic_models import ClinicCashEntryRemoval
    tenant = lock_company(user)
    row = ClinicCashEntry.objects.select_for_update().select_related("session").get(pk=entry_id, session__tenant=tenant)
    if row.status == ClinicCashEntry.Status.CANCELLED or row.session.deleted_at:
        raise ValidationError("Este lançamento já foi apagado.")
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise ValidationError("Informe o motivo para o gestor.")
    pending = ClinicCashEntryRemoval.objects.filter(entry=row, status=ClinicCashEntryRemoval.Status.REQUESTED).first()
    if pending:
        return pending
    item = ClinicCashEntryRemoval.objects.create(entry=row, requested_by=user, reason=reason[:300])
    append_audit(tenant=tenant, user=user, action="clinic.cash_entry.removal_requested", entity_type="ClinicCashEntry",
                 entity_id=row.pk, after={"reason": reason[:300], "total": str(row.total)})
    return item


@transaction.atomic
def decide_removal(*, user, removal_id, approve, note=""):
    from .clinic_models import ClinicCashEntryRemoval
    from .reception_permissions import is_manager as gestor
    tenant = lock_company(user)
    if not gestor(user):
        raise PermissionDenied("Somente o gestor aprova pedidos para apagar lançamentos.")
    item = ClinicCashEntryRemoval.objects.select_for_update().select_related("entry").get(
        pk=removal_id, entry__session__tenant=tenant)
    if item.status != ClinicCashEntryRemoval.Status.REQUESTED:
        raise ValidationError("Este pedido já foi decidido.")
    item.decided_by, item.decided_at, item.decision_note = user, timezone.now(), " ".join((note or "").split())[:300]
    if approve:
        cancel_entry(user=user, entry_id=item.entry_id, reason=f"Pedido da recepção aprovado: {item.reason}"[:300], approved_removal=True)
        item.status = ClinicCashEntryRemoval.Status.APPROVED
    else:
        item.status = ClinicCashEntryRemoval.Status.REJECTED
    item.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
    append_audit(tenant=tenant, user=user, action="clinic.cash_entry.removal_" + ("approved" if approve else "rejected"),
                 entity_type="ClinicCashEntry", entity_id=item.entry_id, after={"note": item.decision_note})
    return item


@transaction.atomic
def delete_sheet(*, user, session_id, reason):
    """Manager deletes a day's cash sheet: its lines are cancelled and the sheet leaves every list (audited)."""
    from .reception_permissions import is_manager as gestor
    tenant = lock_company(user)
    if not gestor(user):
        raise PermissionDenied("Somente o gestor da empresa pode apagar um caixa.")
    session = _lock_session(tenant, session_id)
    if session.deleted_at:
        raise ValidationError("Este caixa já foi apagado.")
    reason = " ".join((reason or "").split())
    if len(reason) < 3:
        raise ValidationError("Informe o motivo para apagar o caixa.")
    if ClinicReceipt.objects.filter(session=session).exists():
        raise ValidationError("Este caixa tem recebimentos de parcelas. Estorne esses recebimentos antes de apagar o caixa.")
    if ClinicCashWithdrawal.objects.filter(session=session, cancelled_at__isnull=True).exists():
        raise ValidationError("Este caixa tem retirada (sangria). Exclua a retirada antes de apagar o caixa.")
    if ClinicExpense.objects.filter(session=session).exclude(transaction__status="cancelled").exists():
        raise ValidationError("Este caixa tem despesas lançadas. Cancele as despesas antes de apagar o caixa.")
    cancelled = 0
    for row in session.clinical_entries.select_for_update().exclude(status=ClinicCashEntry.Status.CANCELLED):
        tx = FinancialTransaction.objects.select_for_update().get(pk=row.transaction_id)
        row.status = ClinicCashEntry.Status.CANCELLED
        row.notes = (f"{row.notes} · " if row.notes else "") + f"Caixa apagado pelo gestor: {reason}"[:200]
        row.save(update_fields=["status", "notes", "updated_at"])
        tx.status = "cancelled"
        tx.save(update_fields=["status", "updated_at"])
        reopen_receivable(tx)
        cancelled += 1
    before = {"status": session.status, "label": session.label, "day": str(session.business_date or "")}
    session.deleted_at, session.deleted_by, session.deleted_reason = timezone.now(), user, reason[:300]
    if session.status == CashSession.Status.OPEN:
        session.status, session.closed_at, session.closed_by = CashSession.Status.CLOSED, timezone.now(), user
    session.save()
    append_audit(tenant=tenant, user=user, action="clinic.cash.deleted", entity_type="CashSession", entity_id=session.pk,
                 before=before, after={"reason": reason[:300], "cancelled_lines": cancelled})
    return session



@transaction.atomic
def cancel_withdrawal(*, user, withdrawal_id, reason):
    """Excluir uma retirada: caixa aberto = quem lançou ou o gestor; caixa fechado = só o gestor, com correção liberada."""
    from .reception_permissions import is_manager as manager
    tenant = lock_company(user)
    row = ClinicCashWithdrawal.objects.select_for_update().select_related("session").get(pk=withdrawal_id, session__tenant=tenant)
    session = _lock_session(tenant, row.session_id)
    reason = " ".join((reason or "").split())[:300]
    if len(reason) < 3:
        raise ValidationError("Informe o motivo para excluir a retirada.")
    if row.cancelled_at:
        return row
    if session.status == CashSession.Status.CLOSED:
        if not (manager(user) and active_correction(session)):
            raise PermissionDenied("Com o caixa fechado, só o gestor exclui uma retirada, pela “Correção do caixa fechado”.")
    elif not (manager(user) or row.recorded_by_id == user.pk):
        raise PermissionDenied("Só quem lançou a retirada ou o gestor pode excluí-la.")
    row.cancelled_at, row.cancelled_by, row.cancel_reason = timezone.now(), user, reason
    row.save(update_fields=["cancelled_at", "cancelled_by", "cancel_reason"])
    append_audit(tenant=tenant, user=user, action="clinic.cash_withdrawal.cancelled", entity_type="ClinicCashWithdrawal",
                 entity_id=row.pk, before={"amount": str(row.amount)}, after={"reason": reason, "session": session.pk})
    refresh_closed(session, user)
    return row


@transaction.atomic
def convert_expense(*, user, expense_id, reason):
    """Gestor corrige uma despesa em dinheiro que era, na verdade, uma retirada. Mantém valor, hora e autor;
    a despesa sai de despesas e do resultado, e a gaveta esperada não muda."""
    from .reception_permissions import is_manager as manager
    if not manager(user):
        raise PermissionDenied("Só o gestor converte despesa em retirada.")
    tenant = lock_company(user)
    expense = ClinicExpense.objects.select_for_update().select_related("transaction", "method").get(pk=expense_id, session__tenant=tenant)
    session = _lock_session(tenant, expense.session_id)
    reason = " ".join((reason or "").split())[:300]
    if len(reason) < 5:
        raise ValidationError("Informe o motivo da conversão.")
    if expense.method.kind != "cash":
        raise ValidationError("Só despesas pagas em dinheiro podem virar retirada de caixa.")
    if ClinicCashWithdrawal.objects.filter(converted_from=expense).exists():
        raise ValidationError("Esta despesa já foi convertida em retirada.")
    tx = FinancialTransaction.objects.select_for_update().get(pk=expense.transaction_id, tenant=tenant)
    if tx.status == "cancelled":
        raise ValidationError("Esta despesa está cancelada.")
    drawer_before = expected_cash(session)
    tx.status = "cancelled"
    tx.save(update_fields=["status", "updated_at"])
    row = ClinicCashWithdrawal.objects.create(
        session=session, amount=tx.amount, method=expense.method, method_name=expense.method_name,
        withdrawn_by="Não informado (convertida de despesa)", destination=ClinicCashWithdrawal.Destination.OTHER,
        notes=f"Convertida da despesa “{tx.description}”: {reason}"[:500], recorded_by=expense.recorded_by,
        occurred_at=expense.created_at, request_id=uuid.uuid4(), converted_from=expense)
    if expected_cash(session) != drawer_before:
        raise ValidationError("A conversão mudaria o dinheiro esperado na gaveta. Nada foi alterado.")
    append_audit(tenant=tenant, user=user, action="clinic.expense.converted_to_withdrawal", entity_type="ClinicExpense",
                 entity_id=expense.pk, before={"expense": expense.pk, "amount": str(tx.amount), "transaction": tx.pk},
                 after={"withdrawal": row.pk, "reason": reason, "session": session.pk})
    refresh_closed(session, user)
    return row


def _day_totals(sessions):
    """Recebido, despesas, retiradas e fundo de um grupo de caixas (para conferir a unificação)."""
    received = expenses = withdrawals = opening = Decimal(0)
    for session in sessions:
        data = report(session)
        received += data["columns"]["total"]
        expenses += data["expenses_total"]
        withdrawals += data["withdrawals_total"]
        opening += session.opening_amount
    return {"received": received, "expenses": expenses, "withdrawals": withdrawals, "opening": opening}


def _merged_conference(closings):
    """Soma a conferência por forma de pagamento dos fechamentos que existiam."""
    merged = {}
    for summary in closings:
        for kind, row in (summary.get("conference") or {}).items():
            item = merged.setdefault(kind, {"expected": Decimal(0), "informed": Decimal(0), "difference": Decimal(0)})
            for key in item:
                item[key] += Decimal(str(row.get(key) or 0))
    return {kind: {k: format(v, ".2f") for k, v in row.items()} for kind, row in merged.items()}


@transaction.atomic
def merge_day(*, user, unit, day):
    """Junta os caixas por profissional de um dia no caixa da clínica. Nada é apagado de verdade: cada caixa
    antigo fica guardado (oculto das listas) e o ClinicCashMerge registra o que saiu dele. Os totais do dia
    (recebido, despesas, retiradas, fundo e dinheiro contado) precisam ficar iguais, senão nada muda."""
    from .clinic_models import ClinicCashCorrection, ClinicCashMerge
    from .clinic_services import period_summary
    from .reception_permissions import is_manager as gestor
    if not gestor(user):
        raise PermissionDenied("Somente o gestor unifica os caixas de um dia.")
    tenant = lock_company(user)
    sessions = list(CashSession.objects.select_for_update().filter(
        tenant=tenant, unit=unit, business_date=day, deleted_at__isnull=True).order_by("pk"))
    if not sessions or (len(sessions) == 1 and not sessions[0].professional_id):
        return None
    before = _day_totals(sessions)
    counted_before = sum((s.closing_amount or Decimal(0) for s in sessions if s.status == CashSession.Status.CLOSED), Decimal(0))
    closings = [c.summary or {} for c in ClinicCashClosing.objects.filter(session__in=sessions)]
    target = next((s for s in sessions if not s.professional_id), sessions[0])
    sources = [s for s in sessions if s.pk != target.pk]
    any_open = any(s.status == CashSession.Status.OPEN for s in sessions)
    target_was = {"professional": target.label, "status": target.status, "opening": str(target.opening_amount),
                  "closing": str(target.closing_amount) if target.closing_amount is not None else None}
    number = target.clinical_entries.aggregate(v=Max("number"))["v"] or 0
    # Linhas do caixa que fica: guardam o profissional dele, que deixa de ser o dono do caixa.
    if target.professional_id:
        ClinicExpense.objects.filter(session=target, professional__isnull=True).update(professional=target.professional)
        ClinicCashWithdrawal.objects.filter(session=target, professional__isnull=True).update(professional=target.professional)
    now = timezone.now()
    for source in sources:
        moved = {"professional": source.label, "status": source.status, "opening": str(source.opening_amount),
                 "closing": str(source.closing_amount) if source.closing_amount is not None else None,
                 "entries": [], "receipts": [], "expenses": [], "withdrawals": [], "corrections": []}
        for row in source.clinical_entries.select_for_update().order_by("number", "pk"):
            number += 1
            moved["entries"].append({"id": row.pk, "number": row.number})
            ClinicCashEntry.objects.filter(pk=row.pk).update(session=target, number=number)
        moved["receipts"] = list(ClinicReceipt.objects.filter(session=source).values_list("pk", flat=True))
        ClinicReceipt.objects.filter(session=source).update(session=target)
        moved["expenses"] = list(ClinicExpense.objects.filter(session=source).values_list("pk", flat=True))
        if source.professional_id:
            ClinicExpense.objects.filter(session=source, professional__isnull=True).update(professional=source.professional)
            ClinicCashWithdrawal.objects.filter(session=source, professional__isnull=True).update(professional=source.professional)
        ClinicExpense.objects.filter(session=source).update(session=target)
        moved["withdrawals"] = list(ClinicCashWithdrawal.objects.filter(session=source).values_list("pk", flat=True))
        ClinicCashWithdrawal.objects.filter(session=source).update(session=target)
        moved["corrections"] = list(ClinicCashCorrection.objects.filter(session=source).values_list("pk", flat=True))
        ClinicCashCorrection.objects.filter(session=source).update(session=target)
        target.opening_amount += source.opening_amount
        target.opened_at = min(target.opened_at, source.opened_at)
        if source.notes:
            target.notes = f"{target.notes}\n{source.label}: {source.notes}".strip()[:500]
        ClinicCashMerge.objects.create(target=target, source=source, moved=moved, merged_by=user)
        source.deleted_at, source.deleted_by = now, user
        source.deleted_reason = f"Unificado no caixa da clínica #{target.pk}"
        if source.status == CashSession.Status.OPEN:
            source.status, source.closed_at, source.closed_by = CashSession.Status.CLOSED, now, user
        source.save()
    target.professional = None
    if any_open:
        target.status, target.closed_at, target.closed_by = CashSession.Status.OPEN, None, None
        target.closing_amount = target.expected_amount = target.difference_amount = None
    else:
        last = max(sessions, key=lambda s: s.closed_at or s.opened_at)
        target.status = CashSession.Status.CLOSED
        target.closed_at, target.closed_by = last.closed_at, last.closed_by
        target.closing_amount = counted_before
    target.save()
    if not any_open:
        target.expected_amount = expected_cash(target)
        target.difference_amount = target.closing_amount - target.expected_amount
        target.save(update_fields=["expected_amount", "difference_amount"])
        data = report(target)
        window = period_summary(tenant, target.unit, target.opened_at, target.closed_at)
        conference = _merged_conference(closings)
        summary = {"professional": target.label, "day": day.isoformat(), "charged": window["charged"],
                   "received": format(data["columns"]["total"], ".2f"), "expenses": format(data["expenses_total"], ".2f"),
                   "withdrawals": format(data["withdrawals_total"], ".2f"),
                   "net": format(data["columns"]["total"] - data["expenses_total"], ".2f"),
                   "pending": format(data["open_total"], ".2f"),
                   "methods": [{"method": label, "type": "income", "amount": format(value, ".2f")} for label, value in data["kinds"]],
                   "opening": str(target.opening_amount), "cash_expected": str(target.expected_amount),
                   "cash_counted": str(target.closing_amount), "difference": str(target.difference_amount),
                   "from": target.opened_at.isoformat(), "to": target.closed_at.isoformat(),
                   "professionals": [{k: (format(v, ".2f") if isinstance(v, Decimal) else v) for k, v in r.items()}
                                     for r in by_professional(target)],
                   "conference": conference, "divergent": [k for k, r in conference.items() if Decimal(r["difference"])],
                   "unified_from": len(sessions)}
        ClinicCashClosing.objects.update_or_create(session=target, defaults={"summary": summary})
    else:
        ClinicCashClosing.objects.filter(session=target).delete()
    after = _day_totals([target])
    if after != before:
        raise ValidationError(f"A unificação de {day:%d/%m/%Y} mudaria os totais do dia. Nada foi alterado.")
    append_audit(tenant=tenant, user=user, action="clinic.cash.unified", entity_type="CashSession", entity_id=target.pk,
                 before={"target": target_was, "sources": [s.pk for s in sources]},
                 after={"day": day.isoformat(), **{k: str(v) for k, v in after.items()}, "status": target.status,
                        "cash_counted": str(target.closing_amount) if target.closing_amount is not None else None})
    return target


def merge_all(*, user, unit):
    """Unifica todos os dias que ainda têm caixas por profissional. Cada dia é independente: um dia com problema
    não impede os outros e é devolvido para conferência."""
    from django.db.models import Count, Q
    days = (CashSession.objects.filter(tenant=user.tenant, unit=unit, deleted_at__isnull=True, business_date__isnull=False)
            .values("business_date").annotate(n=Count("pk"), pros=Count("pk", filter=Q(professional__isnull=False)))
            .filter(Q(n__gt=1) | Q(pros__gt=0)).order_by("business_date"))
    done, failed = [], []
    for item in days:
        try:
            if merge_day(user=user, unit=unit, day=item["business_date"]):
                done.append(item["business_date"])
        except ValidationError as exc:
            failed.append((item["business_date"], " ".join(exc.messages)))
    return done, failed
