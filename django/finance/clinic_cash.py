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
                            ClinicReceipt, ClinicCashClosing)
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
        summary.update({"cash_expected": str(session.expected_amount), "difference": str(session.difference_amount),
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
        description=f"Caixa {day:%d/%m/%Y} · {session.label} · {customer.name}"[:190],
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
    tx.due_at = None if method else timezone.localtime(session.opened_at).date()
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
    """Cash drawer for this sheet: opening + cash received in it - cash expenses in it."""
    entries = session.clinical_entries.filter(status="paid", method__kind="cash").aggregate(v=Sum("total"))["v"] or Decimal(0)
    receipts = ClinicReceipt.objects.filter(session=session, method__kind="cash").aggregate(v=Sum("amount"))["v"] or Decimal(0)
    spent = ClinicExpense.objects.filter(session=session, method__kind="cash").exclude(transaction__status="cancelled").aggregate(
        v=Sum("transaction__amount"))["v"] or Decimal(0)
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
    """Day's closing split per professional: what each dentist produced on this sheet."""
    rows = {}

    def line(name):
        return rows.setdefault(name or "Sem profissional informado", {
            "professional": name or "Sem profissional informado", "patients": 0, "dentist": Decimal(0),
            "clinic": Decimal(0), "other": Decimal(0), "total": Decimal(0), "open": Decimal(0)})

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
    expenses = ClinicExpense.objects.filter(session=session).exclude(transaction__status="cancelled").select_related("transaction")
    opened = timezone.localtime(session.opened_at)
    return {
        "session": session, "entries": entries, "receipts": receipts, "columns": columns,
        "kinds": [(KIND_LABEL[k], by_kind.get(k, Decimal(0))) for k in ("cash", "pix", "card")],
        "kinds_total": sum(by_kind.values(), Decimal(0)),
        "open_rows": open_rows, "open_total": sum((r.total for r in open_rows), Decimal(0)),
        "expenses_total": sum((e.transaction.amount for e in expenses), Decimal(0)),
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

    def clean(self):
        data = super().clean()
        if not data.get("professional") and not (data.get("professional_name") or "").strip():
            self.add_error("professional_name", "Selecione o profissional ou digite o nome de quem atendeu.")
        return data


def _payload(form):
    data = dict(form.cleaned_data)
    data.pop("entry_id", None)
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
                target = session
                chosen = form.cleaned_data.get("professional")
                if session.professional_id and chosen and chosen.pk != session.professional_id:
                    # Each professional has their own sheet for the day: send the line to it.
                    from .clinic_services import day_sheet, session_day
                    with transaction.atomic():
                        target = day_sheet(tenant, session.unit, chosen, request.user, day=session_day(session))
                    messages.info(request, f"Lançado no caixa de {target.label} do mesmo dia.")
                add_entry(user=request.user, session_id=target.pk, **_payload(form))
            elif action == "update" and form.is_valid() and form.cleaned_data.get("entry_id"):
                payload = _payload(form)
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
