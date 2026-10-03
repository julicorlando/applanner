from datetime import timedelta
from decimal import Decimal
import hashlib
from secrets import token_hex

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model,login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.formats import number_format
from django.utils.text import slugify

from accounts.models import PlatformRole,UserRole
from tenants.models import Tenant,Unit,TenantOnboarding
from .models import Module,ModuleRequest,Plan,Subscription,SubscriptionHistory,TenantModuleAddon,PixCharge,Payment,PaymentGateway
from .payment_services import create_platform_subscription,create_platform_pix_charge,platform_provider
from .module_services import cancel_module_addon,module_monthly_price,request_module
from commercial.models import Proposal
from applanner.transactional_email import account_values,queue_email

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


SEGMENT_CATEGORIES={"barbearia":{"barbearia","salao"},"arena":{"arena"},"auto":{"auto"},"saude":{"clinica"}}


def plan_categories(plan,choices):
    segments=(plan.features or {}).get("segments")
    allowed=None if segments is None else set().union(*(SEGMENT_CATEGORIES.get(segment,set()) for segment in segments))
    return [(key,label) for key,label in choices if not key or allowed is None or key in allowed]


class SignupForm(forms.Form):
    proposal_token=forms.CharField(required=False,max_length=32,widget=forms.HiddenInput)
    plan=forms.ModelChoiceField(queryset=Plan.objects.none(),label="Plano")
    billing_cycle=forms.ChoiceField(choices=Subscription.BillingCycle.choices,label="Ciclo")
    payment_method=forms.ChoiceField(
        choices=[("card","Cartão · assinatura automática"),("pix","Pix · pagamento por ciclo")],
        required=False,initial="card",label="Como deseja pagar",
    )
    business_name=forms.CharField(max_length=150,label="Nome do negócio")
    postal_code=forms.CharField(max_length=10,label="CEP da empresa",
        help_text="Usaremos o CEP para posicionar sua unidade no Explorar e mostrar sua empresa para clientes próximos.")
    category=forms.CharField(max_length=60,label="Segmento",widget=forms.Select(choices=[
        ("","Selecione"),("barbearia","Barbearia"),("salao","Salão de beleza"),
        ("estetica","Estética"),("auto","Lava-jato e automotivo"),
        ("arena","Arena e quadras"),
        ("servicos","Outros serviços"),
    ]))
    owner_name=forms.CharField(max_length=150,label="Seu nome")
    email=forms.EmailField(label="E-mail")
    payment_email=forms.EmailField(required=False,label="E-mail de quem pagará (se diferente)",
        help_text="Preencha somente se outra pessoa for responsável pelo pagamento.")
    phone=forms.CharField(max_length=32,required=False,label="Telefone")
    password=forms.CharField(widget=forms.PasswordInput,label="Senha")
    password_confirm=forms.CharField(widget=forms.PasswordInput,label="Confirmar senha")

    def __init__(self,*args,selected_plan=None,**kwargs):
        super().__init__(*args,**kwargs)
        from contenthub.models import PlatformHomepage
        platform=PlatformHomepage.objects.filter(pk=1).first()
        medical_available=bool(platform and platform.medical_segment_visible and Plan.objects.filter(
            slug="segment-medico",active=True,public_visible=True
        ).exists())
        if medical_available:
            self.fields["category"].widget.choices=[
                *self.fields["category"].widget.choices,("clinica","Clínica e saúde")
            ]
        self.fields["plan"].queryset=Plan.objects.filter(
            active=True,public_visible=True,is_custom=False
        ).order_by("sort_order","name")
        self.category_options=list(self.fields["category"].widget.choices)
        if selected_plan:
            self.fields["plan"].initial=selected_plan
            self.fields["category"].widget.choices=plan_categories(selected_plan,self.category_options)

    def clean_postal_code(self):
        import re
        value=re.sub(r"\D","",self.cleaned_data["postal_code"])
        if len(value)!=8:
            raise forms.ValidationError("Informe um CEP brasileiro com 8 dígitos.")
        return value

    def clean_email(self):
        email=self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Já existe uma conta com este e-mail.")
        return email

    def clean(self):
        data=super().clean()
        plan=data.get("plan")
        token=data.get("proposal_token")
        if token:
            proposal=Proposal.objects.filter(public_token=token,status=Proposal.Status.CONVERTED,
                tenant__isnull=True).first()
            if (not proposal or not plan or proposal.plan_id!=plan.pk
                or proposal.expires_at and proposal.expires_at<=timezone.now()
                or proposal.final_price<=0):
                self.add_error("plan","A proposta não está disponível para este plano. Solicite um novo link ao Comercial.")
            elif data.get("billing_cycle")!=Subscription.BillingCycle.MONTHLY:
                self.add_error("billing_cycle","Esta proposta é mensal. Escolha o ciclo mensal.")
            elif proposal.customer_email and proposal.customer_email.lower()!=str(data.get("email") or "").lower():
                self.add_error("email","Use o e-mail indicado na proposta.")
            else:
                current=set(plan.module_links.filter(enabled=True,module__active=True).values_list("module__name",flat=True))
                if current!=set(proposal.modules or []):
                    self.add_error("plan","O catálogo deste plano mudou. Solicite a atualização da proposta.")
        category=(data.get("category") or "").lower()
        if category=="clinica" and not Plan.objects.filter(
            slug="segment-medico",active=True,public_visible=True
        ).exists():
            self.add_error("category","O plano Médico / Clínica ainda não está disponível.")
        if plan and category:
            segment={"barbearia":"barbearia","salao":"barbearia","auto":"auto",
                     "arena":"arena","clinica":"saude"}.get(category)
            if "segments" in (plan.features or {}) and segment not in plan.features["segments"]:
                self.add_error("plan","Este plano não inclui o segmento selecionado. Escolha outro plano ou solicite uma proposta personalizada.")
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
    from contenthub.models import PlatformHomepage
    platform=PlatformHomepage.objects.filter(pk=1).first()
    medical_visible=bool(platform and platform.medical_segment_visible)
    rows=Plan.objects.filter(
        active=True,public_visible=True,is_custom=False
    )
    if not medical_visible:
        rows=rows.exclude(slug="segment-medico")
    rows=rows.prefetch_related("module_links__module").order_by("sort_order","name")
    cards=[]
    for plan in rows:
        modules=[
            link.module for link in plan.module_links.all()
            if link.enabled and link.module.active
        ]
        cards.append({"plan":plan,"modules":modules})
    medical=Plan.objects.filter(slug="segment-medico").first() if medical_visible else None
    catalog={module.pk:module for card in cards for module in card["modules"]}
    comparison=[{"label":module.name,"values":["Incluído" if module in card["modules"] else "Não incluído" for card in cards]}
                for module in sorted(catalog.values(),key=lambda item:(item.sort_order,item.name))]
    arena_cards=["arena" in (card["plan"].features or {}).get("segments",[]) for card in cards]
    def arena_limit(plan,key):
        value=(plan.features or {}).get(key)
        if value==0 and not isinstance(value,bool):
            return "Sem limite"
        return str(value) if value is not None else "Consultar"
    comparison.append({"label":"Profissionais","values":["Não se aplica" if arena else str((card["plan"].features or {}).get("professionals","Consultar")) for card,arena in zip(cards,arena_cards)]})
    if any(arena_cards):
        for key,label in (("courts","Quadras"),("reservations","Reservas por mês")):
            comparison.append({"label":label,"values":[arena_limit(card["plan"],key) if arena else "Não se aplica" for card,arena in zip(cards,arena_cards)]})
    comparison.append({"label":"Unidades","values":[str((card["plan"].features or {}).get("units","Consultar")) for card in cards]})
    for cycle,label in (("quarterly","Trimestral"),("semiannual","Semestral"),("annual","Anual")):
        comparison.append({"label":f"Ciclo {label.lower()}","values":[f"R$ {number_format(_price(card['plan'],cycle),decimal_pos=2)}" for card in cards]})
    return render(request,"billing/plans.html",{"cards":cards,"medical_plan":medical,"comparison":comparison})


class CustomPlanForm(forms.Form):
    name=forms.CharField(max_length=160,label="Seu nome")
    business_type=forms.CharField(max_length=100,label="Tipo de negócio")
    email=forms.EmailField(label="E-mail")
    phone=forms.CharField(max_length=30,label="Telefone")
    modules=forms.ModelMultipleChoiceField(queryset=Module.objects.none(),widget=forms.CheckboxSelectMultiple,label="Funções desejadas")
    consent=forms.BooleanField(label="Autorizo o contato para receber uma proposta do ApPlanner")

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["modules"].queryset=Module.objects.filter(active=True).order_by("sort_order","name")


def custom_plan(request):
    from commercial.models import Lead
    from growth.attribution import acquisition_context,capture_attribution,record_acquisition

    capture_attribution(request)
    form=CustomPlanForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        data=form.cleaned_data
        Lead.objects.create(
            name=data["name"],business_type=data["business_type"],
            email=data["email"],phone=data["phone"],
            source="custom_plan",consent_granted=True,
            consent_at=timezone.now(),consent_version="custom_plan_v1",
            consent_purpose="Contato comercial para proposta de plano personalizado",
            notes="Módulos solicitados: "+", ".join(module.name for module in data["modules"]),
        )
        record_acquisition(request,"Lead",segment=data["business_type"])
        messages.success(request,"Recebemos sua seleção. Nossa equipe entrará em contato para montar sua proposta.")
        return redirect("billing-custom-plan")
    return render(request,"billing/custom_plan.html",{"form":form})


def signup(request):
    from growth.attribution import capture_attribution,record_acquisition
    capture_attribution(request)
    plan_id=request.POST.get("plan") if request.method=="POST" else request.GET.get("plan")
    plan_id=plan_id if plan_id and plan_id.isascii() and plan_id.isdigit() and len(plan_id)<=19 and int(plan_id)<=2**63-1 else None
    selected=Plan.objects.filter(
        pk=plan_id,active=True,public_visible=True,is_custom=False
    ).first() if plan_id else None
    proposal=Proposal.objects.filter(public_token=request.GET.get("proposal", "")[:32],
        status=Proposal.Status.CONVERTED,tenant__isnull=True).first() if request.GET.get("proposal") else None
    form=SignupForm(request.POST or None,selected_plan=selected)
    plan_conditions=[{"id":str(plan.pk),"name":plan.name,"days":plan.trial_days,"withoutCard":plan.trial_without_card,
        "categories":[{"value":value,"label":label} for value,label in plan_categories(plan,form.category_options)],
        "prices":{cycle:number_format(_price(plan,cycle),decimal_pos=2) for cycle,_ in Subscription.BillingCycle.choices}}
        for plan in form.fields["plan"].queryset]
    if request.method!="POST" and request.GET.get("proposal"):
        form.fields["proposal_token"].initial=request.GET["proposal"][:32]
    if request.method=="POST" and form.is_valid():
        data=form.cleaned_data
        plan=data["plan"]
        cycle=data["billing_cycle"]
        now=timezone.now()
        trial_days=int(plan.trial_days or 0)
        trial_end=now+timedelta(days=trial_days) if trial_days else None
        contracted=Decimal(str(_price(plan,cycle))).quantize(Decimal("0.01"))
        with transaction.atomic():
            proposal=None
            if data.get("proposal_token"):
                proposal=Proposal.objects.select_for_update().filter(
                    public_token=data["proposal_token"],status=Proposal.Status.CONVERTED,
                    tenant__isnull=True,plan=plan,
                ).first()
                if not proposal:
                    form.add_error("plan","Esta proposta já foi contratada ou expirou.")
                    return render(request,"billing/signup.html",{"form":form,"selected_plan":selected,"plan_conditions":plan_conditions})
                contracted=proposal.final_price
            slug=_unique_slug(data["business_name"])
            tenant=Tenant.objects.create(
                name=data["business_name"],slug=slug,public_slug=slug,
                email=data["email"],phone=data["phone"],category=data["category"],
                status=Tenant.Status.TRIAL if trial_days else Tenant.Status.ACTIVE,
                public_enabled=False,public_booking_enabled=True,
            )
            unit=Unit.objects.create(
                tenant=tenant,name=data["business_name"],is_primary=True,
                postal_code=data["postal_code"],
                email=data["email"],phone=data["phone"],active=True,
            )
            TenantOnboarding.objects.create(tenant=tenant,required=True)
            user=User.objects.create_user(
                email=data["email"],password=data["password"],tenant=tenant,
                first_name=data["owner_name"],role="owner",is_active=True,
            )
            queue_email(tenant,user.email,"account_created",
                account_values(user,base_url=request.build_absolute_uri("/")))
            tenant_admin=PlatformRole.objects.filter(slug="tenant-admin").first()
            if tenant_admin:
                UserRole.objects.get_or_create(user=user,role=tenant_admin)
            subscription=Subscription.objects.create(
                tenant=tenant,plan=plan,billing_cycle=cycle,
                contracted_price=contracted,base_contracted_price=contracted,addon_contracted_price=0,
                status=Subscription.Status.TRIAL if trial_days else Subscription.Status.PAST_DUE,
                started_at=now,trial_started_at=now if trial_days else None,
                trial_ends_at=trial_end,trial_days_snapshot=trial_days,
                next_billing_at=trial_end or now,
            )
            if proposal:
                proposal.tenant=tenant
                proposal.save(update_fields=["tenant","updated_at"])
            record_acquisition(request,"CompleteRegistration",tenant=tenant,user=user,segment=data["category"])
            context=acquisition_context(request)
            from commercial.models import Lead
            referrer_id=request.session.get("referral_user_id")
            lead=Lead.objects.create(
                name=data["owner_name"],phone=data["phone"] or "",email=data["email"],
                business_type=data["category"],estimated_value=contracted,
                source=(context.get("source") or "organic")[:80],
                source_medium=(context.get("medium") or "")[:80],
                source_campaign=(context.get("campaign") or "")[:120],
                status=Lead.Status.CONVERTED,
                referrer_user_id=referrer_id if referrer_id else None,
                converted_tenant=tenant,
                consent_granted=True,consent_version="signup_v1",
                consent_purpose="Cadastro e contratação do ApPlanner",
                consent_at=now,
            )
            from engagement.referrals import create_referral_reward_from_signup
            create_referral_reward_from_signup(request,tenant)
            transaction.on_commit(lambda unit_id=unit.pk: __import__(
                "tenants.tasks",fromlist=["geocode_unit_from_postal_code"]
            ).geocode_unit_from_postal_code.delay(unit_id))
        for key in ("referral_code","referral_campaign_id","referral_user_id"):
            request.session.pop(key,None)
        login(request,user,backend="django.contrib.auth.backends.ModelBackend")
        request.session["session_version"]=user.session_version

        needs_payment=(not plan.trial_without_card) or not trial_days
        if needs_payment:
            try:
                payer_email=data.get("payment_email") or user.email
                if data.get("payment_method")=="pix":
                    create_platform_pix_charge(subscription=subscription,payer_email=payer_email)
                    return redirect("billing-subscription-pix")
                remote=create_platform_subscription(
                    subscription=subscription,payer_email=payer_email,
                    back_url=request.build_absolute_uri("/billing/assinatura/"),
                    idempotency_key="signup-"+hashlib.sha256(
                        f"{tenant.pk}|{subscription.pk}|{cycle}|{payer_email}".encode()
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
        return redirect("tenant-onboarding")
    return render(request,"billing/signup.html",{"form":form,"selected_plan":selected,"proposal":proposal,"plan_conditions":plan_conditions})


@login_required
def subscription_status(request):
    from billing.entitlements import professional_capacity
    from billing.segment_access import segment_enabled
    subscription=(
        Subscription.objects.filter(tenant=request.user.tenant)
        .select_related("plan").order_by("-started_at").first()
        if request.user.tenant_id else None
    )
    pix_charge=(PixCharge.objects.select_related("payment").filter(
        subscription=subscription,payment__status=Payment.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at").first() if subscription else None)
    from operations.models import SupportTicket
    pending_deletion=(SupportTicket.objects.filter(tenant_id=request.user.tenant_id,
        category="account_deletion").exclude(status__in=[SupportTicket.Status.CLOSED,SupportTicket.Status.RESOLVED])
        .order_by("-created_at").first() if request.user.tenant_id else None)
    return render(request,"billing/subscription_status.html",{"subscription":subscription,"pix_charge":pix_charge,
        "professional_capacity":professional_capacity(request.user.tenant,subscription) if request.user.tenant_id and not segment_enabled(request.user.tenant,"arena") else None,
        "pending_deletion":pending_deletion,"can_manage":request.user.tenant_id and request.user.role=="owner"})


@login_required
@require_POST
def cancel_platform_subscription(request):
    if not request.user.tenant_id or request.user.role!="owner":
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Somente o titular pode cancelar a assinatura.")
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request,"Senha incorreta. A assinatura não foi alterada.")
        return redirect("billing-subscription-status")
    with transaction.atomic():
        subscription=(Subscription.objects.select_for_update().filter(tenant_id=request.user.tenant_id)
                      .order_by("-started_at").first())
        if not subscription or subscription.status==Subscription.Status.CANCELLED:
            messages.info(request,"Esta assinatura já está cancelada.")
            return redirect("billing-subscription-status")
        if subscription.provider_subscription_id:
            gateway=PaymentGateway.objects.filter(provider="mercadopago",active=True,
                last_test_status=PaymentGateway.TestStatus.VALIDATED).first()
            if not gateway:
                messages.error(request,"Conexão do Mercado Pago indisponível. Abra um chamado antes de cancelar.")
                return redirect("billing-subscription-status")
            try:
                remote=platform_provider(gateway).cancel_subscription(subscription.provider_subscription_id)
                if remote.get("status") not in {"canceled","cancelled"}:
                    raise RuntimeError("Cancelamento não confirmado pelo Mercado Pago.")
            except (RuntimeError,ValueError):
                messages.error(request,"O Mercado Pago não confirmou o cancelamento. Sua assinatura não foi alterada; contate o suporte.")
                return redirect("billing-subscription-status")
        previous=subscription.status
        subscription.status=Subscription.Status.CANCELLED
        subscription.cancelled_at=timezone.now()
        subscription.next_billing_at=None
        subscription.provider_checkout_url=""
        subscription.save(update_fields=["status","cancelled_at","next_billing_at","provider_checkout_url","updated_at"])
        SubscriptionHistory.objects.create(subscription=subscription,tenant=subscription.tenant,
            from_plan=subscription.plan,to_plan=subscription.plan,from_status=previous,
            to_status=subscription.status,reason="Cancelamento solicitado pelo titular")
    messages.success(request,"Assinatura cancelada. Os pagamentos anteriores e seus dados permanecem registrados.")
    return redirect("billing-subscription-status")


@login_required
@require_POST
def request_account_deletion(request):
    if not request.user.tenant_id or request.user.role!="owner":
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Somente o titular pode solicitar a exclusão da conta da empresa.")
    if not request.user.check_password(request.POST.get("password", "")):
        messages.error(request,"Senha incorreta. Nenhuma solicitação foi criada.")
        return redirect("billing-subscription-status")
    from operations.models import BillingSupportRequest,SupportTicket
    from operations.triage import classify_priority
    with transaction.atomic():
        pending=SupportTicket.objects.select_for_update().filter(tenant_id=request.user.tenant_id,
            category="account_deletion").exclude(status__in=[SupportTicket.Status.CLOSED,SupportTicket.Status.RESOLVED]).first()
        if pending:
            BillingSupportRequest.objects.get_or_create(
                ticket=pending,
                defaults={
                    "tenant":request.user.tenant,
                    "user":request.user,
                    "request_type":BillingSupportRequest.RequestType.ACCOUNT_DELETION,
                    "status":BillingSupportRequest.Status.PENDING,
                },
            )
            messages.info(request,f"Solicitação em análise: {pending.protocol}.")
        else:
            ticket=SupportTicket.objects.create(protocol="EX-"+token_hex(8).upper(),
                tenant=request.user.tenant,user=request.user,category="account_deletion",
                subject="Solicitação de exclusão de conta e dados",
                description=(request.POST.get("reason") or "Titular solicitou exclusão da conta.")[:2000],
                priority=classify_priority("privacidade","Solicitação de exclusão de conta",""))
            BillingSupportRequest.objects.create(
                tenant=request.user.tenant,user=request.user,ticket=ticket,
                request_type=BillingSupportRequest.RequestType.ACCOUNT_DELETION,
                status=BillingSupportRequest.Status.PENDING,
            )
            messages.success(request,f"Pedido {ticket.protocol} recebido. A equipe analisará dados, pagamentos e obrigações de conservação antes de concluir a exclusão.")
    return redirect("billing-subscription-status")


@login_required
def subscription_pix(request):
    if not request.user.tenant_id or request.user.role not in {"owner","manager"}:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Somente o responsável pode iniciar o pagamento da assinatura.")
    subscription=Subscription.objects.filter(tenant=request.user.tenant).order_by("-started_at").first()
    if not subscription or subscription.status not in {Subscription.Status.TRIAL,Subscription.Status.PAST_DUE}:
        messages.error(request,"Não há cobrança pendente para esta assinatura.")
        return redirect("billing-subscription-status")
    if request.method=="POST":
        try:
            payer_email=forms.EmailField().clean(request.POST.get("payment_email") or request.user.email)
            create_platform_pix_charge(subscription=subscription,payer_email=payer_email)
        except (RuntimeError,ValueError,ValidationError) as exc:
            messages.error(request,"Não foi possível gerar o Pix: "+str(exc))
            return redirect("billing-subscription-status")
        return redirect("billing-subscription-pix")
    charge=PixCharge.objects.select_related("payment").filter(
        subscription=subscription,payment__status=Payment.Status.PENDING,
        expires_at__gt=timezone.now(),
    ).order_by("-created_at").first()
    if not charge:
        return redirect("billing-subscription-status")
    return render(request,"billing/subscription_pix.html",{"charge":charge,"subscription":subscription})


@login_required
def subscription_checkout(request):
    if request.method!="POST":
        return redirect("billing-subscription-status")
    if not request.user.tenant_id or request.user.role not in {"owner","manager"}:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("Somente o responsável pode iniciar o pagamento da assinatura.")
    subscription=Subscription.objects.filter(tenant=request.user.tenant).order_by("-started_at").first()
    if not subscription or subscription.status not in {Subscription.Status.TRIAL,Subscription.Status.PAST_DUE}:
        messages.error(request,"Não há cobrança pendente para esta assinatura.")
        return redirect("billing-subscription-status")
    if PixCharge.objects.filter(subscription=subscription,payment__status=Payment.Status.PENDING,expires_at__gt=timezone.now()).exists():
        messages.info(request,"Já existe um Pix pendente. Confira o código antes de iniciar outra cobrança.")
        return redirect("billing-subscription-pix")
    if subscription.provider_subscription_id:
        if subscription.provider_checkout_url.startswith("https://"):
            return redirect(subscription.provider_checkout_url)
        messages.info(request,"Já existe uma autorização de cobrança iniciada. Entre em contato com o suporte se precisar de um novo link.")
        return redirect("billing-subscription-status")
    try:
        payer_email=forms.EmailField().clean(request.POST.get("payment_email") or request.user.email)
        remote=create_platform_subscription(
            subscription=subscription,payer_email=payer_email,
            back_url=request.build_absolute_uri("/billing/assinatura/"),
            idempotency_key=f"customer-checkout-{subscription.pk}-"+hashlib.sha256(payer_email.encode()).hexdigest()[:16],
        )
    except (RuntimeError,ValueError,ValidationError) as exc:
        messages.error(request,"Não foi possível iniciar o pagamento: "+str(exc))
        return redirect("billing-subscription-status")
    url=remote.get("init_point") or ""
    if url.startswith("https://"):
        return redirect(url)
    messages.error(request,"O provedor não disponibilizou um link seguro de pagamento.")
    return redirect("billing-subscription-status")


@login_required
def subscription_modules(request):
    if not request.user.tenant_id:
        messages.error(request,"Selecione uma empresa.")
        return redirect("billing-subscription-status")
    tenant=request.user.tenant
    subscription=Subscription.objects.filter(tenant=tenant).select_related("plan").order_by("-started_at").first()
    if not subscription:
        messages.error(request,"Assinatura não encontrada.")
        return redirect("billing-subscription-status")
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="request":
                module=get_object_or_404(Module,pk=request.POST.get("module"),active=True)
                row=request_module(tenant=tenant,module=module,user=request.user,note=request.POST.get("note",""))
                messages.success(request,f"Solicitação de {row.module.name} enviada ao Master.")
            elif action=="cancel":
                addon=get_object_or_404(TenantModuleAddon,pk=request.POST.get("addon"),tenant=tenant)
                cancel_module_addon(addon=addon,user=request.user)
                messages.success(request,"Módulo adicional cancelado e assinatura atualizada.")
            else:
                raise ValidationError("Ação inválida.")
        except (ValidationError,RuntimeError,ValueError) as exc:
            messages.error(request,str(exc))
        return redirect("billing-subscription-modules")

    plan_module_ids=set(
        subscription.plan.module_links.filter(enabled=True).values_list("module_id",flat=True)
    )
    active_ids=set(
        TenantModuleAddon.objects.filter(
            tenant=tenant,status=TenantModuleAddon.Status.ACTIVE
        ).values_list("module_id",flat=True)
    )
    pending_ids=set(
        ModuleRequest.objects.filter(
            tenant=tenant,status__in=[
                ModuleRequest.Status.PENDING,ModuleRequest.Status.APPROVED,
                ModuleRequest.Status.AWAITING_PAYMENT,ModuleRequest.Status.ACTIVE,
            ]
        ).values_list("module_id",flat=True)
    )
    available=list(Module.objects.filter(
        active=True,addon_sellable=True
    ).exclude(pk__in=plan_module_ids|active_ids|pending_ids).order_by("sort_order","name"))
    for module in available:
        module.current_monthly_price=module_monthly_price(module,tenant)
        module.current_unit_count=tenant.units.filter(active=True).count() if module.per_unit_billing else None
    return render(request,"billing/modules.html",{
        "subscription":subscription,"available":available,
        "requests":ModuleRequest.objects.filter(tenant=tenant).select_related("module").order_by("-created_at")[:100],
        "active_addons":TenantModuleAddon.objects.filter(
            tenant=tenant,status=TenantModuleAddon.Status.ACTIVE
        ).select_related("module").order_by("module__name"),
    })
