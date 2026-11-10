from datetime import date, timedelta
from decimal import Decimal
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from billing.entitlements import module_enabled
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from accounts.permissions import require_any_capability
from tenants.models import Tenant
from tenants.groups import BusinessGroup, GroupCompany, GroupRoyalty
from finance.dre import report
from finance.models import FinancialTransaction, FinancialCategory
from .audit import append_audit


class GroupForm(forms.ModelForm):
    class Meta:
        model = BusinessGroup
        fields = ["name"]
        labels = {"name": "Nome do grupo / franquia"}


class InviteForm(forms.Form):
    slug = forms.SlugField(label="Identificador público da empresa")
    rate = forms.DecimalField(
        label="Percentual de royalties proposto",
        min_value=0,
        max_value=100,
        decimal_places=2,
        max_digits=5,
    )


def month(value):
    try:
        d = date.fromisoformat(value + "-01")
        if not 2000 <= d.year <= 2100:
            raise ValueError
    except (ValueError, TypeError):
        raise ValidationError("Informe um mês válido.") from None
    next_month = (
        d.replace(year=d.year + 1, month=1)
        if d.month == 12
        else d.replace(month=d.month + 1)
    )
    return d, next_month - timedelta(days=1)


@login_required
def dashboard(request):
    require_any_capability(request.user, "finance.manage")
    if request.user.role in {"professional", "reception"}:
        raise PermissionDenied
    user = request.user
    tenant = user.tenant if user.tenant_id else None
    if tenant and not user.is_superuser and not module_enabled(tenant, "finance"):
        raise PermissionDenied
    groups = BusinessGroup.objects.filter(owner=user, active=True)
    group = (
        get_object_or_404(
            groups, pk=request.GET.get("group") or request.POST.get("group")
        )
        if request.GET.get("group") or request.POST.get("group")
        else groups.first()
    )
    form = GroupForm(request.POST if request.POST.get("action") == "create" else None)
    invite = InviteForm(
        request.POST if request.POST.get("action") == "invite" else None
    )
    error = None
    if request.method == "POST":
        try:
            with transaction.atomic():
                action = request.POST.get("action")
                if action == "create" and form.is_valid():
                    group = form.save(commit=False)
                    group.owner = user
                    group.save()
                    if tenant:
                        append_audit(
                            tenant=tenant,
                            user=user,
                            action="BUSINESS_GROUP_CREATED",
                            entity_type="BusinessGroup",
                            entity_id=group.pk,
                        )
                elif action == "invite" and group and invite.is_valid():
                    target = (
                        Tenant.objects.filter(
                            public_enabled=True,
                            deleted_at__isnull=True,
                            archived_at__isnull=True,
                        )
                        .filter(
                            Q(public_slug=invite.cleaned_data["slug"])
                            | Q(
                                public_slug__isnull=True,
                                slug=invite.cleaned_data["slug"],
                            )
                        )
                        .first()
                    )
                    if not target:
                        raise ValidationError(
                            "Empresa pública não encontrada. Use o identificador da página pública."
                        )
                    company, created = GroupCompany.objects.get_or_create(
                        group=group,
                        tenant=target,
                        defaults={"royalty_percent": invite.cleaned_data["rate"]},
                    )
                    if not created:
                        raise ValidationError(
                            "Essa empresa já possui convite ou vínculo. A aprovação é feita na própria empresa."
                        )
                    if tenant:
                        append_audit(
                            tenant=tenant,
                            user=user,
                            action="GROUP_COMPANY_INVITED",
                            entity_type="GroupCompany",
                            entity_id=company.pk,
                            after={"rate": company.royalty_percent},
                        )
                elif action in {"accept", "revoke", "approve_royalty"}:
                    if not tenant:
                        raise PermissionDenied
                    company = get_object_or_404(
                        GroupCompany.objects.select_for_update(),
                        pk=request.POST.get("company"),
                        tenant=tenant,
                    )
                    if action in {"accept", "revoke"} and getattr(
                        request, "support_actor", None
                    ):
                        raise PermissionDenied
                    if (
                        action in {"accept", "revoke"}
                        and not user.is_superuser
                        and user.role not in {"owner", "tenant-admin", "manager"}
                    ):
                        raise PermissionDenied
                    if action == "accept":
                        if company.status != "pending":
                            raise ValidationError("Convite não está pendente.")
                        company.status = "active"
                        company.approved_by = user
                        company.approved_at = timezone.now()
                        company.save()
                    elif action == "revoke":
                        company.status = "revoked"
                        company.save(update_fields=["status", "updated_at"])
                    else:
                        royalty = get_object_or_404(
                            GroupRoyalty.objects.select_for_update(),
                            pk=request.POST.get("royalty"),
                            company=company,
                        )
                        if company.status != "active":
                            raise ValidationError("Compartilhamento revogado.")
                        if not royalty.expense_id:
                            category, _ = FinancialCategory.objects.get_or_create(
                                tenant=tenant,
                                name="Royalties de franquia",
                                defaults={
                                    "type": "expense",
                                    "statement_line": "operating_expenses",
                                    "expense_nature": "variable",
                                },
                            )
                            royalty.expense = FinancialTransaction.objects.create(
                                tenant=tenant,
                                category=category,
                                type="expense",
                                description=f"Royalties {company.group.name} · {royalty.period:%m/%Y}",
                                amount=royalty.amount,
                                status="pending",
                                competence_at=royalty.period,
                                idempotency_key=f"royalty:{royalty.pk}",
                                source_type="group_royalty",
                                source_id=royalty.pk,
                            )
                            royalty.approved_by = user
                            royalty.approved_at = timezone.now()
                            royalty.save()
                    append_audit(
                        tenant=tenant,
                        user=user,
                        action="GROUP_" + action.upper(),
                        entity_type="GroupCompany",
                        entity_id=company.pk,
                    )
                elif action == "accrue" and group:
                    company = get_object_or_404(
                        GroupCompany.objects.select_for_update(),
                        group=group,
                        pk=request.POST.get("company"),
                        status="active",
                    )
                    first, last = month(request.POST.get("period", ""))
                    if last >= timezone.localdate():
                        raise ValidationError(
                            "Apure royalties somente de meses encerrados."
                        )
                    result = report(company.tenant, first, last)
                    gross = max(
                        next(
                            row["amount"]
                            for row in result["sections"]
                            if row["key"] == "gross_revenue"
                        ),
                        Decimal(0),
                    )
                    royalty, created = GroupRoyalty.objects.get_or_create(
                        company=company,
                        period=first,
                        defaults={
                            "revenue_snapshot": gross,
                            "rate_snapshot": company.royalty_percent,
                            "amount": (gross * company.royalty_percent / 100).quantize(
                                Decimal(".01")
                            ),
                        },
                    )
                    if created:
                        append_audit(
                            tenant=company.tenant,
                            user=user,
                            action="GROUP_ROYALTY_PROPOSED",
                            entity_type="GroupRoyalty",
                            entity_id=royalty.pk,
                            after={"amount": royalty.amount, "period": first},
                        )
                else:
                    raise ValidationError("Confira os dados da ação.")
            from django.urls import reverse

            return redirect(
                reverse("business-groups") + (f"?group={group.pk}" if group else "")
            )
        except ValidationError as exc:
            error = " ".join(exc.messages)
    try:
        first, last = month(
            request.GET.get("period") or timezone.localdate().strftime("%Y-%m")
        )
    except ValidationError:
        first, last = month(timezone.localdate().strftime("%Y-%m"))
        error = "Mês inválido; exibindo o mês atual."
    rows = []
    if group:
        for company in group.companies.filter(status="active").select_related("tenant"):
            if company.tenant.deleted_at or company.tenant.archived_at:
                continue
            result = report(company.tenant, first, last)
            rows.append(
                {
                    "company": company,
                    "result": result,
                    "revenue": next(
                        r["amount"]
                        for r in result["sections"]
                        if r["key"] == "gross_revenue"
                    ),
                }
            )
    return render(
        request,
        "portal/business_groups.html",
        {
            "groups": groups,
            "group": group,
            "form": form,
            "invite": invite,
            "error": error,
            "rows": rows,
            "period": first.strftime("%Y-%m"),
            "links": GroupCompany.objects.filter(tenant=tenant).select_related("group")
            if tenant
            else [],
            "royalties": GroupRoyalty.objects.filter(
                company__tenant=tenant
            ).select_related("company__group", "expense")
            if tenant
            else [],
            "proposals": GroupRoyalty.objects.filter(
                company__group=group
            ).select_related("company__tenant")
            if group
            else [],
        },
    )
