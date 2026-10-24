import secrets
from decimal import Decimal, InvalidOperation
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from accounts.permissions import require_any_capability
from billing.entitlements import module_enabled
from core.unit_scope import selected_unit
from core.audit import append_audit
from scheduling.models import Professional, Service
from barber.models import BarberCommand
from .portal import _tenant
from .models import (
    FinancialCategory,
    CommissionPolicy,
    CommissionTier,
    GiftCard,
    GiftCardEntry,
    Product,
)
from .statement import PeriodForm
from .dre import report, cash_flow
from . import giftcards


def access(request):
    require_any_capability(request.user, "finance.manage")
    if request.user.role in {"professional", "reception"}:
        raise PermissionDenied
    tenant = _tenant(request)
    if not request.user.is_superuser and not module_enabled(tenant, "finance"):
        raise PermissionDenied
    return tenant


class CategoryForm(forms.ModelForm):
    class Meta:
        model = FinancialCategory
        fields = ["name", "type", "statement_line", "expense_nature", "active"]
        labels = {
            "name": "Categoria",
            "type": "Tipo",
            "statement_line": "Linha da DRE",
            "expense_nature": "Natureza da despesa",
            "active": "Ativa",
        }


@login_required
def dre(request):
    tenant = access(request)
    unit = (
        None
        if request.GET.get("scope") == "company"
        else selected_unit(request, tenant)
    )
    from django.utils import timezone

    today = timezone.localdate()
    form = PeriodForm(request.GET or {"start": today.replace(day=1), "end": today})
    result = (
        report(tenant, form.cleaned_data["start"], form.cleaned_data["end"], unit)
        if form.is_valid()
        else None
    )
    return render(
        request,
        "finance/dre.html",
        {
            "form": form,
            "report": result,
            "unit": unit,
            "tenant": tenant,
            "cash_flow": cash_flow(
                tenant, form.cleaned_data["start"], form.cleaned_data["end"], unit
            )
            if form.is_valid()
            else None,
        },
    )


@login_required
def categories(request):
    tenant = access(request)
    row = (
        get_object_or_404(
            FinancialCategory,
            tenant=tenant,
            pk=request.GET.get("edit") or request.POST.get("category"),
        )
        if request.GET.get("edit") or request.POST.get("category")
        else FinancialCategory(tenant=tenant)
    )
    form = CategoryForm(request.POST or None, instance=row)
    if request.method == "POST" and form.is_valid():
        if (
            FinancialCategory.objects.filter(
                tenant=tenant, name=form.cleaned_data["name"]
            )
            .exclude(pk=row.pk)
            .exists()
        ):
            form.add_error("name", "Já existe uma categoria com esse nome.")
        else:
            form.save()
            append_audit(
                tenant=tenant,
                user=request.user,
                action="DRE_CATEGORY_CONFIGURED",
                entity_type="FinancialCategory",
                entity_id=row.pk,
                after={"line": row.statement_line, "nature": row.expense_nature},
            )
            return redirect("finance-categories")
    return render(
        request,
        "finance/market_form.html",
        {
            "title": "Plano de contas e DRE",
            "description": "Classifique receitas, custos, tributos e despesas. Compras de estoque/ativo não entram como despesa na DRE; o CMV usa snapshots das vendas. Lançamentos sem classificação são sinalizados.",
            "form": form,
            "rows": FinancialCategory.objects.filter(tenant=tenant),
            "edit": row.pk,
            "back": "finance-dre",
            "edit_key": "category",
        },
    )


class PolicyForm(forms.ModelForm):
    tier_lines = forms.CharField(
        label="Faixas: meta mensal; percentual (uma por linha)",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Exemplo: 0;30 e 1000;40. A taxa atingida vale para este evento; não altera comissões anteriores.",
    )

    class Meta:
        model = CommissionPolicy
        fields = [
            "name",
            "professional",
            "service",
            "product",
            "starts_on",
            "ends_on",
            "deduct_materials",
            "active",
        ]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "name": "Nome",
            "professional": "Profissional",
            "service": "Serviço (vazio: todos)",
            "product": "Produto específico",
            "starts_on": "Início da vigência",
            "ends_on": "Fim da vigência",
            "deduct_materials": "Descontar insumos antes do percentual",
            "active": "Ativar política",
        }

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant
        self.fields["professional"].queryset = Professional.objects.filter(
            tenant=tenant, active=True
        )
        self.fields["service"].queryset = Service.objects.filter(
            tenant=tenant, active=True
        )
        self.fields["product"].queryset = Product.objects.filter(
            tenant=tenant, active=True, kind="retail"
        )
        if self.instance.pk:
            self.fields["tier_lines"].initial = "\n".join(
                f"{row.threshold};{row.rate}" for row in self.instance.tiers.all()
            )

    def clean_tier_lines(self):
        result = []
        try:
            for line in self.cleaned_data["tier_lines"].splitlines():
                if not line.strip():
                    continue
                parts = line.replace(",", ".").split(";")
                if len(parts) != 2:
                    raise ValueError
                threshold, rate = map(Decimal, parts)
                if (
                    not threshold.is_finite()
                    or not rate.is_finite()
                    or threshold < 0
                    or threshold > Decimal("9999999999.99")
                    or not 0 <= rate <= 100
                    or threshold != threshold.quantize(Decimal(".01"))
                    or rate != rate.quantize(Decimal(".01"))
                ):
                    raise ValueError
                result.append((threshold, rate))
            if (
                not 1 <= len(result) <= 20
                or min(x[0] for x in result) != 0
                or len({x[0] for x in result}) != len(result)
            ):
                raise ValueError
        except (ValueError, InvalidOperation):
            raise forms.ValidationError(
                "Informe até 20 faixas válidas, metas únicas e a primeira meta zero."
            ) from None
        return sorted(result)


@login_required
def policies(request):
    tenant = access(request)
    row = (
        get_object_or_404(
            CommissionPolicy,
            tenant=tenant,
            pk=request.GET.get("edit") or request.POST.get("policy"),
        )
        if request.GET.get("edit") or request.POST.get("policy")
        else CommissionPolicy(tenant=tenant)
    )
    form = PolicyForm(request.POST or None, tenant=tenant, instance=row)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            policy = form.save()
            CommissionPolicy.objects.select_for_update().get(pk=policy.pk)
            policy.tiers.all().delete()
            CommissionTier.objects.bulk_create(
                [
                    CommissionTier(policy=policy, threshold=t, rate=r)
                    for t, r in form.cleaned_data["tier_lines"]
                ]
            )
            append_audit(
                tenant=tenant,
                user=request.user,
                action="COMMISSION_POLICY_CONFIGURED",
                entity_type="CommissionPolicy",
                entity_id=policy.pk,
                after={
                    "active": policy.active,
                    "starts_on": policy.starts_on,
                    "tiers": [
                        (str(t), str(r)) for t, r in form.cleaned_data["tier_lines"]
                    ],
                },
            )
        return redirect("finance-policies")
    return render(
        request,
        "finance/market_form.html",
        {
            "title": "Comissões por metas e vigência",
            "description": "Metas acumulam receitas dos eventos comissionados do mês. Políticas específicas prevalecem sobre a geral. Vigências sobrepostas impedem fechamento até a correção. A dedução usa custos reais de insumos vinculados ao atendimento; cada cálculo fica congelado no extrato.",
            "form": form,
            "rows": CommissionPolicy.objects.filter(tenant=tenant),
            "edit": row.pk,
            "back": "finance-commissions",
            "edit_key": "policy",
        },
    )


class GiftIssueForm(forms.Form):
    amount = forms.DecimalField(
        label="Valor recebido",
        max_digits=12,
        decimal_places=2,
        min_value=Decimal(".01"),
    )
    method = forms.ChoiceField(
        label="Pagamento recebido",
        choices=[
            ("cash", "Dinheiro"),
            ("pix", "Pix"),
            ("card", "Cartão"),
            ("transfer", "Transferência"),
        ],
    )
    expires = forms.DateField(
        label="Validade (opcional)",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    key = forms.CharField(max_length=100, widget=forms.HiddenInput)


class GiftRedeemForm(forms.Form):
    code = forms.CharField(
        label="Código do vale",
        max_length=40,
        widget=forms.PasswordInput(render_value=False),
    )
    command = forms.ModelChoiceField(
        label="Comanda aberta", queryset=BarberCommand.objects.none()
    )
    amount = forms.DecimalField(
        label="Valor a usar", max_digits=12, decimal_places=2, min_value=Decimal(".01")
    )
    key = forms.CharField(max_length=100, widget=forms.HiddenInput)


@login_required
def gifts(request):
    tenant = access(request)
    unit = selected_unit(request, tenant)
    action = request.POST.get("action")
    issue = GiftIssueForm(
        request.POST if action == "issue" else None,
        initial={"key": secrets.token_urlsafe(24)},
        prefix="issue",
    )
    redeem = GiftRedeemForm(
        request.POST if action == "redeem" else None,
        initial={"key": secrets.token_urlsafe(24)},
        prefix="redeem",
    )
    redeem.fields["command"].queryset = BarberCommand.objects.filter(
        tenant=tenant, status="open"
    )
    code = None
    if request.method == "POST":
        try:
            if action == "issue" and issue.is_valid():
                card, code = giftcards.issue(
                    tenant=tenant, user=request.user, unit=unit, **issue.cleaned_data
                )
                if not code:
                    messages.info(
                        request,
                        "Emissão já registrada. O código completo é exibido somente uma vez.",
                    )
            elif action == "redeem" and redeem.is_valid():
                giftcards.redeem(
                    tenant=tenant, user=request.user, **redeem.cleaned_data
                )
                messages.success(
                    request,
                    "Saldo aplicado como pagamento da comanda, sem duplicar a receita.",
                )
                return redirect("finance-gifts")
            elif action == "reverse":
                giftcards.reverse(
                    tenant=tenant,
                    user=request.user,
                    entry_id=request.POST.get("entry"),
                    key=request.POST.get("key"),
                )
                return redirect("finance-gifts")
        except (
            ValidationError,
            IntegrityError,
            GiftCardEntry.DoesNotExist,
            ValueError,
        ) as exc:
            messages.error(
                request,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Operação inválida ou identificador já utilizado.",
            )
    return render(
        request,
        "finance/gifts.html",
        {
            "issue": issue,
            "redeem": redeem,
            "code": code,
            "rows": GiftCard.objects.filter(tenant=tenant).order_by("-created_at")[
                :100
            ],
            "entries": GiftCardEntry.objects.filter(
                tenant=tenant,
                kind="redeem",
                command__status="open",
                reversed_entry__isnull=True,
            )
            .exclude(
                pk__in=GiftCardEntry.objects.filter(
                    tenant=tenant, kind="reversal"
                ).values("reversed_entry_id")
            )
            .select_related("card", "command"),
            "key": secrets.token_urlsafe(24),
        },
    )
