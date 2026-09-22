from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render

from tenants.models import Tenant
from .domains import create_tenant_domain,verify_tenant_domain
from .models import TenantDomain


def _tenant(request):
    if request.user.tenant_id:return request.user.tenant
    if request.user.is_superuser:
        tid=request.session.get("portal_tenant_id")
        if tid:return Tenant.objects.filter(pk=tid).first()
    raise PermissionDenied("Selecione uma empresa.")


class DomainForm(forms.Form):
    domain=forms.CharField(max_length=190,label="Domínio")


@login_required
def domains(request):
    tenant=_tenant(request)
    form=DomainForm(request.POST or None)
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="create" and form.is_valid():
                create_tenant_domain(tenant=tenant,domain=form.cleaned_data["domain"])
                messages.success(request,"Domínio adicionado. Configure o TXT mostrado abaixo.")
            elif action=="verify":
                row=get_object_or_404(TenantDomain,pk=request.POST.get("domain_id"),tenant=tenant)
                if verify_tenant_domain(row):
                    messages.success(request,"Domínio verificado com sucesso.")
                else:
                    messages.error(request,"TXT de verificação ainda não foi encontrado.")
        except ValidationError as exc: messages.error(request,str(exc))
        return redirect("engagement-domains")
    return render(request,"engagement/domains.html",{
        "form":form,"rows":TenantDomain.objects.filter(tenant=tenant).order_by("-created_at"),
    })


from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404,redirect,render

from scheduling.models import Appointment,Customer,Service
from tenants.models import Tenant
from .models import (
    CustomerMembership,CustomerPackage,LoyaltyAccount,LoyaltyReferral,LoyaltyReward,
    ServicePackage,TenantLoyaltySettings,WaitlistEntry,
)
from .services import (
    complete_referral,consume_package_credit,create_membership,earn_points,issue_reward,
    match_waitlist,purchase_package,redeem_reward,
)


def _tenant(request):
    if request.user.tenant_id:return request.user.tenant
    if request.user.is_superuser:
        tid=request.session.get("portal_tenant_id")
        if tid:return Tenant.objects.filter(pk=tid).first()
    raise PermissionDenied("Selecione uma empresa.")


class PurchaseForm(forms.Form):
    customer=forms.ModelChoiceField(queryset=Customer.objects.none())
    package=forms.ModelChoiceField(queryset=ServicePackage.objects.none())
    amount=forms.DecimalField(required=False,min_value=0,decimal_places=2,max_digits=12)
    def __init__(self,*args,tenant=None,recurring=False,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["customer"].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by("name")
        self.fields["package"].queryset=ServicePackage.objects.filter(tenant=tenant,active=True,recurring=recurring).order_by("name")


class MembershipForm(PurchaseForm):
    cycle=forms.ChoiceField(choices=CustomerMembership.Cycle.choices)
    online_payment=forms.BooleanField(required=False,label="Criar recorrência no Mercado Pago")
    payer_email=forms.EmailField(required=False,label="E-mail do pagador")


class ConsumeForm(forms.Form):
    customer_package=forms.ModelChoiceField(queryset=CustomerPackage.objects.none(),label="Pacote do cliente")
    service=forms.ModelChoiceField(queryset=Service.objects.none())
    appointment=forms.ModelChoiceField(queryset=Appointment.objects.none(),required=False)
    credits=forms.IntegerField(min_value=1,initial=1)
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["customer_package"].queryset=CustomerPackage.objects.filter(tenant=tenant,status=CustomerPackage.Status.ACTIVE).select_related("customer","package")
        self.fields["service"].queryset=Service.objects.filter(tenant=tenant,active=True)
        self.fields["appointment"].queryset=Appointment.objects.filter(tenant=tenant).order_by("-starts_at")[:500]


class PointsForm(forms.Form):
    customer=forms.ModelChoiceField(queryset=Customer.objects.none())
    amount=forms.DecimalField(min_value=0.01,decimal_places=2,max_digits=12,label="Valor da compra")
    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["customer"].queryset=Customer.objects.filter(tenant=tenant,active=True).order_by("name")


@login_required
def packages(request):
    tenant=_tenant(request)
    buy=PurchaseForm(tenant=tenant,prefix="buy")
    membership=MembershipForm(tenant=tenant,recurring=True,prefix="membership")
    consume=ConsumeForm(tenant=tenant,prefix="consume")
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="buy":
                buy=PurchaseForm(request.POST,tenant=tenant,prefix="buy")
                if buy.is_valid():
                    purchase_package(tenant=tenant,**buy.cleaned_data)
                    messages.success(request,"Pacote vendido ao cliente.")
            elif action=="membership":
                membership=MembershipForm(request.POST,tenant=tenant,recurring=True,prefix="membership")
                if membership.is_valid():
                    d=membership.cleaned_data
                    obj=create_membership(
                        tenant=tenant,customer=d["customer"],package=d["package"],cycle=d["cycle"],
                        amount=d["amount"],payer_email=d["payer_email"],
                        back_url=(settings.PUBLIC_BASE_URL or request.build_absolute_uri("/")).rstrip("/")+"/",
                        online_payment=d["online_payment"],
                    )
                    if getattr(obj,"checkout_url",""):
                        messages.success(request,f"Recorrência criada. Checkout: {obj.checkout_url}")
                    else: messages.success(request,"Mensalidade criada.")
            elif action=="consume":
                consume=ConsumeForm(request.POST,tenant=tenant,prefix="consume")
                if consume.is_valid():
                    consume_package_credit(user=request.user,**consume.cleaned_data)
                    messages.success(request,"Crédito consumido.")
        except (ValidationError,RuntimeError,ValueError) as exc: messages.error(request,str(exc))
        return redirect("engagement-packages")
    return render(request,"engagement/packages.html",{
        "buy":buy,"membership":membership,"consume":consume,
        "customer_packages":CustomerPackage.objects.filter(tenant=tenant).select_related("customer","package").order_by("-purchased_at")[:100],
        "memberships":CustomerMembership.objects.filter(tenant=tenant).select_related("customer","package").order_by("next_due_at")[:100],
    })


@login_required
def loyalty(request):
    tenant=_tenant(request)
    settings_obj,_=TenantLoyaltySettings.objects.get_or_create(tenant=tenant)
    points_form=PointsForm(tenant=tenant)
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="settings":
                settings_obj.enabled=request.POST.get("enabled")=="on"
                settings_obj.points_per_currency=Decimal(request.POST.get("points_per_currency") or "1")
                settings_obj.reward_points=int(request.POST.get("reward_points") or 100)
                settings_obj.reward_value=Decimal(request.POST.get("reward_value") or "10")
                settings_obj.referral_points=int(request.POST.get("referral_points") or 50)
                settings_obj.save()
                messages.success(request,"Regras de fidelidade atualizadas.")
            elif action=="earn":
                points_form=PointsForm(request.POST,tenant=tenant)
                if points_form.is_valid():
                    d=points_form.cleaned_data
                    earned=earn_points(tenant=tenant,customer=d["customer"],amount=d["amount"],source_type="manual_sale",source_id=None,user=request.user,note="Lançamento manual")
                    messages.success(request,f"{earned} pontos adicionados.")
            elif action=="issue":
                customer=get_object_or_404(Customer,pk=request.POST.get("customer"),tenant=tenant)
                issue_reward(tenant=tenant,customer=customer,user=request.user)
                messages.success(request,"Recompensa emitida.")
            elif action=="redeem":
                reward=get_object_or_404(LoyaltyReward,pk=request.POST.get("reward"),tenant=tenant)
                redeem_reward(reward=reward,user=request.user)
                messages.success(request,"Recompensa resgatada.")
            elif action=="referral":
                referral=get_object_or_404(LoyaltyReferral,pk=request.POST.get("referral"),tenant=tenant)
                complete_referral(referral=referral,user=request.user)
                messages.success(request,"Indicação concluída e pontos creditados.")
        except (ValidationError,ValueError) as exc: messages.error(request,str(exc))
        return redirect("engagement-loyalty")
    return render(request,"engagement/loyalty.html",{
        "settings":settings_obj,"points_form":points_form,
        "accounts":LoyaltyAccount.objects.filter(tenant=tenant).select_related("customer").order_by("-points")[:200],
        "rewards":LoyaltyReward.objects.filter(tenant=tenant,status=LoyaltyReward.Status.AVAILABLE).select_related("customer"),
        "referrals":LoyaltyReferral.objects.filter(tenant=tenant,status=LoyaltyReferral.Status.PENDING).select_related("referrer","referred"),
    })


@login_required
def waitlist(request):
    tenant=_tenant(request)
    if request.method=="POST":
        entry=get_object_or_404(WaitlistEntry,pk=request.POST.get("entry"),tenant=tenant)
        try:
            match_waitlist(entry=entry,user=request.user)
            messages.success(request,"Entrada marcada como encontrada/notificada.")
        except ValidationError as exc: messages.error(request,str(exc))
        return redirect("engagement-waitlist")
    return render(request,"engagement/waitlist.html",{
        "rows":WaitlistEntry.objects.filter(tenant=tenant).select_related("customer","service","professional").order_by("preferred_date","created_at")[:200]
    })
