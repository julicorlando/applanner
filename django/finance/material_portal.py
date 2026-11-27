import secrets
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from accounts.permissions import require_any_capability
from billing.entitlements import module_enabled
from core.portal import _require_tenant
from scheduling.models import Service
from .models import Product, ServiceMaterial, MaterialConsumption
from .advanced_services import consume_material


class RecipeForm(forms.ModelForm):
    class Meta:
        model = ServiceMaterial
        fields = ["service", "product", "quantity", "active"]
        labels = {
            "service": "Serviço",
            "product": "Insumo",
            "quantity": "Quantidade por atendimento",
            "active": "Ativar consumo automático",
        }

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant = tenant
        self.fields["service"].queryset = Service.objects.filter(
            tenant=tenant, active=True
        )
        self.fields["product"].queryset = Product.objects.filter(
            tenant=tenant, kind="internal", active=True
        )


class ConsumptionForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none(), label="Insumo")
    quantity = forms.DecimalField(
        min_value=Decimal("0.001"), decimal_places=3, max_digits=12, label="Quantidade utilizada"
    )
    note = forms.CharField(max_length=300, label="Motivo / observação")
    key = forms.CharField(max_length=100, widget=forms.HiddenInput)

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            tenant=tenant, kind="internal", active=True
        )


@login_required
def materials(request):
    require_any_capability(request.user, "finance.manage")
    if request.user.role in {"professional", "reception"}:
        raise PermissionDenied
    tenant = _require_tenant(request)
    if not tenant:
        return redirect("portal-home")
    if not (
        request.user.is_superuser
        or module_enabled(tenant, "stock")
        or module_enabled(tenant, "products")
    ):
        raise PermissionDenied
    action = request.POST.get("action")
    editing = None
    raw_recipe = request.GET.get("edit") or request.POST.get("recipe_id")
    if raw_recipe:
        editing = get_object_or_404(ServiceMaterial, pk=raw_recipe, tenant=tenant)
    recipe = RecipeForm(
        request.POST if request.method == "POST" and action == "recipe" else None,
        tenant=tenant,
        instance=editing,
        prefix="recipe",
    )
    consume = ConsumptionForm(
        request.POST if request.method == "POST" and action == "consume" else None,
        tenant=tenant,
        initial={"key": secrets.token_urlsafe(24)},
        prefix="consume",
    )
    if request.method == "POST":
        if action == "recipe" and recipe.is_valid():
            recipe.save()
            messages.success(
                request,
                "Ficha de consumo cadastrada. A baixa ocorre ao concluir o atendimento.",
            )
            return redirect("finance-materials")
        if action == "consume" and consume.is_valid():
            data = consume.cleaned_data
            try:
                consume_material(
                    tenant=tenant,
                    product_id=data["product"].pk,
                    quantity=data["quantity"],
                    user=request.user,
                    key=data["key"],
                    note=data["note"],
                )
            except (ValidationError, Product.DoesNotExist) as exc:
                consume.add_error(None, exc)
            else:
                messages.success(
                    request, "Consumo interno registrado, sem venda ou comissão."
                )
                return redirect("finance-materials")
        if action == "disable":
            row = get_object_or_404(
                ServiceMaterial, pk=request.POST.get("recipe"), tenant=tenant
            )
            row.active = False
            row.save(update_fields=["active", "updated_at"])
            messages.success(request, "Ficha desativada para os próximos atendimentos.")
            return redirect("finance-materials")
    return render(
        request,
        "finance/materials.html",
        {
            "tenant": tenant,
            "recipe": recipe,
            "editing": editing,
            "consume": consume,
            "recipes": ServiceMaterial.objects.filter(tenant=tenant).select_related(
                "service", "product"
            ),
            "rows": MaterialConsumption.objects.filter(tenant=tenant)
            .select_related("product", "user")
            .order_by("-created_at")[:100],
        },
    )
