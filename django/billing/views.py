from datetime import timedelta
from decimal import Decimal
import hashlib

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model,login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import PlatformRole,UserRole
from tenants.models import Tenant,Unit
from .models import Plan,Subscription
from .payment_services import create_platform_subscription

User=get_user_model()


def _price(plan,cycle):
    return {
        Subscription.BillingCycle.MONTHLY:plan.monthly_price,
        Subscription.BillingCycle.QUARTERLY:plan.quarterly_price or plan.monthly_price*3,
        Subscription.BillingCycle.SEMIANNUAL:plan.semiannual_price or plan.monthly_price*6,
        Subscription.BillingCycle.ANNUAL:plan.annual_price or plan.monthly_price*12,
    }[cycle]


def _unique_slug(name):
    base=slugify(name)[:100] or "empresa"
    slug=base
    index=2
    while Tenant.objects.filter(slug=slug).exists():
        suffix=f"-{index}"
        slug=(base[:120-len(suffix)]+suffix)
        index+=1
    return slug


class SignupForm(forms.Form):
    plan=forms.ModelChoiceField(queryset=Plan.objects.none(),label="Plano")
    billing_cycle=forms.ChoiceField(choices=Subscription.BillingCycle.choices,label="Ciclo")
    business_name=forms.CharField(max_length=150,label="Nome do negócio")
    category=forms.CharField(max_length=60,required=False,label="Segmento")
    owner_name=forms.CharField(max_length=150,label="Seu nome")
    email=forms.EmailField(label="E-mail")
    phone=forms.CharField(max_length=32,required=False,label="Telefone")
    password=forms.CharField(widget=forms.PasswordInput,label="Senha")
    password_confirm=forms.CharField(widget=forms.PasswordInput,label="Confirmar senha")

    def __init__(self,*args,selected_plan=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["plan"].queryset=Plan.objects.filter(
            active=True,public_visible=True,is_custom=False
        ).order_by("sort_order","name")
        if selected_plan:
            self.fields["plan"].initial=selected_plan

    def clean_email(self):
        email=self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail.")
        return email

    def clean(self):
        data=super().clean()
        password=data.get("password") or ""
        if password and password!=data.get("password_confirm"):
            self.add_error("password_confirm","As senhas não conferem.")
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password",exc)
        return data


def plans(request):
    rows=Plan.objects.filter(
        active=True,public_visible=True,is_custom=False
    ).prefetch_related("module_links__module").order_by("sort_order","name")
    cards=[]
    for plan in rows:
        modules=[
            link.module for link in plan.module_links.all()
            if link.enabled and link.module.active
        ]
        cards.append({"plan":plan,"modules":modules})
    return render(request,"billing/plans.html",{"cards":cards})


def signup(request):
    plan_id=request.GET.get("plan") or request.POST.get("plan")
    selected=Plan.objects.filter(
        pk=plan_id,active=True,public_visible=True,is_custom=False
    ).first() if plan_id else None
    form=SignupForm(request.POST or None,selected_plan=selected)
    if request.method=="POST" and form.is_valid():
        data=form.cleaned_data
        plan=data["plan"]
        cycle=data["billing_cycle"]
        now=timezone.now()
        trial_days=int(plan.trial_days or 0)
        trial_end=now+timedelta(days=trial_days) if trial_days else None
        contracted=Decimal(str(_price(plan,cycle))).quantize(Decimal("0.01"))
        with transaction.atomic():
            slug=_unique_slug(data["business_name"])
            tenant=Tenant.objects.create(
                name=data["business_name"],slug=slug,public_slug=slug,
                email=data["email"],phone=data["phone"],category=data["category"],
                status=Tenant.Status.TRIAL if trial_days else Tenant.Status.ACTIVE,
                public_enabled=False,public_booking_enabled=True,
            )
            Unit.objects.create(
                tenant=tenant,name=data["business_name"],is_primary=True,
                email=data["email"],phone=data["phone"],active=True,
            )
            user=User.objects.create_user(
                email=data["email"],password=data["password"],tenant=tenant,
                first_name=data["owner_name"],role="owner",is_active=True,
            )
            tenant_admin=PlatformRole.objects.filter(slug="tenant-admin").first()
            if tenant_admin:
                UserRole.objects.get_or_create(user=user,role=tenant_admin)
            subscription=Subscription.objects.create(
                tenant=tenant,plan=plan,billing_cycle=cycle,
                contracted_price=contracted,
                status=Subscription.Status.TRIAL if trial_days else Subscription.Status.PAST_DUE,
                started_at=now,trial_started_at=now if trial_days else None,
                trial_ends_at=trial_end,trial_days_snapshot=trial_days,
                next_billing_at=trial_end or now,
            )
        login(request,user,backend="django.contrib.auth.backends.ModelBackend")
        request.session["session_version"]=user.session_version

        needs_payment=(not plan.trial_without_card) or not trial_days
        if needs_payment:
            try:
                remote=create_platform_subscription(
                    subscription=subscription,payer_email=user.email,
                    back_url=request.build_absolute_uri("/billing/assinatura/"),
                    idempotency_key="signup-"+hashlib.sha256(
                        f"{tenant.pk}|{subscription.pk}|{cycle}".encode()
                    ).hexdigest()[:56],
                )
                if remote.get("init_point"):
                    return redirect(remote["init_point"])
            except (RuntimeError,ValueError) as exc:
                messages.warning(
                    request,
                    "Conta criada, mas a cobrança ainda não pôde ser iniciada: "+str(exc),
                )
        messages.success(request,"Conta criada. Bem-vindo ao ApPlanner.")
        return redirect("home")
    return render(request,"billing/signup.html",{"form":form,"selected_plan":selected})


@login_required
def subscription_status(request):
    subscription=(
        Subscription.objects.filter(tenant=request.user.tenant)
        .select_related("plan").order_by("-started_at").first()
        if request.user.tenant_id else None
    )
    return render(request,"billing/subscription_status.html",{"subscription":subscription})
