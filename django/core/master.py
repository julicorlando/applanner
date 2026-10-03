from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from requests.exceptions import RequestException

from billing.models import Module, Plan, PlanModule
from billing.models import PaymentGateway
from billing.payment_services import configure_mercadopago_gateway
from core.labels import field_label


FIELD_LABELS={
    "name":"Nome","slug":"Identificador","description":"Descrição","category":"Segmento",
    "monthly_price":"Valor mensal","quarterly_price":"Valor trimestral","semiannual_price":"Valor semestral",
    "annual_price":"Valor anual","trial_days":"Dias de teste grátis","trial_without_card":"Teste sem cartão",
    "active":"Ativo","public_visible":"Visível na página de planos","is_custom":"Plano personalizado",
    "featured":"Em destaque","sort_order":"Ordem de exibição","public_enabled":"Página pública ativa",
    "public_booking_enabled":"Agendamento público ativo","email":"E-mail","phone":"Telefone",
    "status":"Situação","request_type":"Tipo de solicitação","created_at":"Criado em","updated_at":"Atualizado em",
    "provider_environment":"Ambiente da assinatura no provedor",
    "professional_limit_override":"Liberação de profissionais para esta empresa",
}


class PlanMasterForm(forms.ModelForm):
    segments=forms.MultipleChoiceField(
        choices=[("barbearia","Barbearia e salão"),("auto","Automotivo e lava-jato"),
                 ("arena","Arena e quadras"),("saude","Clínica e saúde")],
        widget=forms.CheckboxSelectMultiple,required=False,label="Segmentos incluídos no plano",
    )
    professionals_limit=forms.IntegerField(min_value=1,required=False,label="Limite de profissionais")
    units_limit=forms.IntegerField(min_value=1,required=False,label="Limite de unidades")
    courts_limit=forms.IntegerField(min_value=0,required=False,label="Limite de quadras ativas",
        help_text="Arena: zero significa sem limite; vazio significa não definido. Ajustes não desativam quadras existentes.")
    reservations_limit=forms.IntegerField(min_value=0,required=False,label="Limite de reservas por mês",
        help_text="Arena: zero significa sem limite. Conta reservas não canceladas pela data do atendimento, no fuso da empresa.")
    included_features=forms.CharField(
        required=False,label="Funcionalidades comerciais",
        widget=forms.Textarea(attrs={"rows":8,"placeholder":"Uma funcionalidade por linha"}),
    )

    class Meta:
        model=Plan
        fields=[
            "name","slug","description","monthly_price","quarterly_price","semiannual_price",
            "annual_price","trial_days","trial_without_card","active","public_visible",
            "is_custom","featured","sort_order",
        ]

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for key,field in self.fields.items():
            if key in FIELD_LABELS:field.label=FIELD_LABELS[key]
        features=(getattr(self.instance,"features",None) or {}) if self.instance else {}
        self.fields["professionals_limit"].initial=features.get("professionals")
        self.fields["units_limit"].initial=features.get("units")
        self.fields["courts_limit"].initial=features.get("courts")
        self.fields["reservations_limit"].initial=features.get("reservations")
        self.fields["segments"].initial=features.get("segments",[value for value,_ in self.fields["segments"].choices])
        self.fields["included_features"].initial="\n".join(features.get("included_features") or [])

    def save(self,commit=True):
        obj=super().save(commit=False)
        features=dict(obj.features or {})
        if self.cleaned_data.get("professionals_limit"):
            features["professionals"]=self.cleaned_data["professionals_limit"]
        else:
            features.pop("professionals",None)
        if self.cleaned_data.get("units_limit"):
            features["units"]=self.cleaned_data["units_limit"]
        else:
            features.pop("units",None)
        features["segments"]=self.cleaned_data["segments"]
        for key in ("courts","reservations"):
            value=self.cleaned_data.get(f"{key}_limit")
            if value is None:
                features.pop(key,None)
            else:
                features[key]=value
        if "arena" in self.cleaned_data["segments"]:
            features["arena_limits_configured"]=True
        features["included_features"]=[
            line.strip() for line in (self.cleaned_data.get("included_features") or "").splitlines()
            if line.strip()
        ][:30]
        obj.features=features
        if commit:
            obj.save()
        return obj


class TenantMasterForm(forms.ModelForm):
    courts_limit_override=forms.IntegerField(min_value=0,required=False,label="Liberação de quadras para esta empresa",
        help_text="Vazio: seguir o plano. Zero: sem limite. Outro número: limite autorizado pelo Master.")
    reservations_limit_override=forms.IntegerField(min_value=0,required=False,label="Liberação de reservas mensais para esta empresa",
        help_text="Vazio: seguir o plano. Zero: sem limite. Outro número: limite autorizado pelo Master.")
    professional_limit_override=forms.IntegerField(min_value=0,required=False,
        label="Liberação de profissionais para esta empresa",
        help_text="Vazio: seguir o plano. Zero: sem limite. Outro número: limite autorizado pelo Master, inclusive no teste grátis.")

    class Meta:
        from tenants.models import Tenant
        model=Tenant
        fields=["name","slug","public_slug","category","email","phone","logo","cover","status",
                "public_enabled","public_booking_enabled","locale","timezone"]

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["professional_limit_override"].initial=(self.instance.metadata or {}).get("professional_limit_override")
        for key in ("courts","reservations"):
            self.fields[f"{key}_limit_override"].initial=(self.instance.metadata or {}).get(f"{key}_limit_override")

    def save(self,commit=True):
        obj=super().save(commit=False)
        obj.metadata={**(obj.metadata or {})}
        for key in ("courts","reservations"):
            field=f"{key}_limit_override"
            value=self.cleaned_data.get(field)
            if value is None:
                obj.metadata.pop(field,None)
            else:
                obj.metadata[field]=value
        value=self.cleaned_data.get("professional_limit_override")
        if value is None:
            obj.metadata.pop("professional_limit_override",None)
        else:
            obj.metadata["professional_limit_override"]=value
        if commit:
            obj.save()
        return obj


class UserMasterForm(forms.ModelForm):
    new_password=forms.CharField(
        label="Senha inicial",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}),
        help_text="O usuário deverá trocar esta senha no primeiro acesso.",
    )
    confirm_password=forms.CharField(
        label="Confirmar senha",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}),
    )

    class Meta:
        model=apps.get_model("accounts","User")
        fields=["tenant","email","role","is_active","is_staff"]

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk:
            self.fields["new_password"].required=False
            self.fields["confirm_password"].required=False
            self.fields["new_password"].help_text="Deixe vazio para manter a senha atual."

    def clean(self):
        data=super().clean()
        password=data.get("new_password")
        confirmation=data.get("confirm_password")
        if password and password!=confirmation:
            self.add_error("confirm_password","As senhas não conferem.")
        elif confirmation and not password:
            self.add_error("new_password","Informe a nova senha.")
        if password:
            try:
                validate_password(password,self.instance)
            except ValidationError as exc:
                self.add_error("new_password",exc)
        return data

    def save(self,commit=True):
        obj=super().save(commit=False)
        password=self.cleaned_data.get("new_password")
        if password:
            obj.set_password(password)
            obj.must_change_password=True
            if obj.pk:
                obj.session_version+=1
        if commit:
            obj.save()
        return obj


MASTER_RESOURCES={
    "empresas":{"model":"tenants.Tenant","title":"Empresas","fields":["name","slug","public_slug","category","email","phone","logo","cover","status","public_enabled","public_booking_enabled","locale","timezone"],"columns":["name","slug","category","status","public_enabled","created_at"],"order":"-created_at"},
    "planos":{"model":"billing.Plan","title":"Planos","fields":["name","slug","description","monthly_price","quarterly_price","semiannual_price","annual_price","trial_days","trial_without_card","active","public_visible","is_custom","featured","sort_order"],"columns":["name","monthly_price","trial_days","active","public_visible","is_custom","featured"],"order":"sort_order,name","special":"plan"},
    "modulos":{"model":"billing.Module","title":"Módulos","fields":["name","slug","description","addon_monthly_price","addon_sellable","per_unit_billing","sort_order","active"],"columns":["name","slug","addon_monthly_price","addon_sellable","active"],"order":"sort_order,name"},
    "solicitacoes-modulos":{"model":"billing.ModuleRequest","title":"Solicitações de módulos","fields":[],"columns":["tenant","module","quoted_monthly_price","status","created_at"],"order":"-created_at","create":False,"edit":False},
    "equipe-comercial":{"model":"commercial.CommercialProfile","title":"Equipe comercial","fields":["user","commission_percent","max_discount_percent","support_enabled","active"],"columns":["user","commission_percent","max_discount_percent","support_enabled","active"],"order":"user__email"},
    "comissoes-comerciais":{"model":"commercial.CommercialCommission","title":"Comissões comerciais","fields":["commercial_user","tenant","base_amount","commission_percent","commission_amount","status","hold_until"],"columns":["commercial_user","tenant","commission_amount","status","created_at"],"order":"-created_at"},
    "assinaturas":{"model":"billing.Subscription","title":"Assinaturas","fields":["tenant","plan","billing_cycle","contracted_price","status","started_at","trial_ends_at","next_billing_at","provider_customer_id","provider_subscription_id","provider_environment"],"columns":["tenant","plan","billing_cycle","status","next_billing_at"],"order":"-started_at"},
    "financeiro":{"model":"finance.PlatformFinancialTransaction","title":"Financeiro da plataforma","fields":["category","type","description","amount","status","due_at","paid_at","notes"],"columns":["type","description","amount","status","due_at"],"order":"-created_at","special":"platform_finance"},
    "suporte":{"model":"operations.SupportTicket","title":"Suporte","fields":["tenant","user","category","subject","description","priority","status","assigned_to"],"columns":["protocol","tenant","subject","priority","status","assigned_to"],"order":"-created_at","create":False},
    "incidentes":{"model":"operations.OperationalIncident","title":"Incidentes","fields":["category","severity","title","details","status"],"columns":["severity","title","status","occurrence_count","last_seen_at"],"order":"-last_seen_at","create":False},
    "backups":{"model":"operations.Backup","title":"Backups","fields":[],"columns":["type","scope","status","destination","size_bytes","completed_at"],"order":"-started_at","create":False,"edit":False},
    "homologacao":{"model":"operations.HomologationRun","title":"Homologações","fields":[],"columns":["status","score","executed_by","created_at"],"order":"-created_at","create":False,"edit":False},
    "legais":{"model":"legal.LegalDocument","title":"Documentos legais","fields":["type","version","title","content","status","requires_acceptance","published_at"],"columns":["type","version","title","status","published_at"],"order":"-published_at,-created_at"},
    "comerciais":{"model":"commercial.CommercialProfile","title":"Equipe comercial","fields":["user","commission_percent","max_discount_percent","support_enabled","active"],"columns":["user","commission_percent","max_discount_percent","support_enabled","active"],"order":"user__email"},
    "comissoes-comerciais":{"model":"commercial.CommercialCommission","title":"Comissões comerciais","fields":[],"columns":["commercial_user","tenant","base_amount","commission_amount","status","paid_at"],"order":"-created_at","create":False,"edit":False},
    "leads":{"model":"commercial.Lead","title":"Leads comerciais","fields":[],"columns":["name","business_type","source","source_medium","source_campaign","referrer_user","converted_tenant","status","assigned_to","next_contact_at","created_at"],"order":"-created_at","create":False,"edit":False},
    "propostas":{"model":"commercial.Proposal","title":"Propostas comerciais","fields":[],"columns":["title","customer_name","commercial_user","final_price","status","approval_status"],"order":"-created_at","create":False,"edit":False},
    "operacao":{"model":"operations.PlatformOperationSettings","title":"Configuração operacional","fields":["backup_retention_days","backup_include_uploads","backup_encrypt","backup_before_update","lead_retention_days","critical_alert_email","critical_alerts_enabled","cron_stale_minutes","disk_min_free_mb"],"columns":["backup_retention_days","backup_include_uploads","critical_alerts_enabled","cron_stale_minutes","disk_min_free_mb"],"order":"id","special":"operation_settings"},
    "crons":{"model":"operations.CronHeartbeat","title":"Saúde dos jobs","fields":[],"columns":["cron_key","status","started_at","finished_at","duration_ms","host_name"],"order":"-started_at","create":False,"edit":False},
    "imports":{"model":"operations.DataImportJob","title":"Implantações de bases","fields":[],"columns":["tenant","source","original_name","status","created_at","completed_at"],"order":"-created_at","create":False,"edit":False},
    "fila-php-legada":{"model":"operations.LegacyRuntimeJob","title":"Fila PHP legada","fields":[],"columns":["id","tenant","type","status","attempts","available_at","failed_at"],"order":"-id","create":False,"edit":False},
    "falhas-php-legadas":{"model":"operations.LegacyFailedJobArchive","title":"Falhas da fila PHP","fields":[],"columns":["id","tenant","type","status","attempts","failed_at"],"order":"-id","create":False,"edit":False},
    "migrations-php":{"model":"operations.LegacyMigrationRecord","title":"Migrations PHP legadas","fields":[],"columns":["id","migration","batch","executed_at"],"order":"id","create":False,"edit":False},
    "isencoes-assinaturas":{"model":"billing.SubscriptionExemption","title":"Isenções de assinatura","fields":["tenant","subscription","exemption_type","starts_at","ends_at","reason","status"],"columns":["tenant","subscription","exemption_type","starts_at","ends_at","status"],"order":"-created_at","special":"subscription_exemption"},
    "historico-assinaturas":{"model":"billing.SubscriptionHistory","title":"Histórico de assinaturas","fields":[],"columns":["tenant","subscription","from_plan","to_plan","from_status","to_status","reason","created_at"],"order":"-created_at","create":False,"edit":False},
    "addons-modulos":{"model":"billing.TenantModuleAddon","title":"Módulos adicionais contratados","fields":[],"columns":["tenant","module","monthly_price","status","started_at","next_billing_at"],"order":"-created_at","create":False,"edit":False},
    "ajustes-modulos":{"model":"billing.SubscriptionModuleAdjustment","title":"Ajustes de módulos na assinatura","fields":[],"columns":["tenant","subscription","action","previous_amount","new_amount","status","created_at"],"order":"-created_at","create":False,"edit":False},
    "checkouts":{"model":"billing.CheckoutSession","title":"Checkouts","fields":[],"columns":["public_id","tenant","plan","billing_cycle","total","status","expires_at"],"order":"-created_at","create":False,"edit":False},
    "cupons":{"model":"billing.Coupon","title":"Cupons","fields":["code","type","value","valid_from","valid_until","max_uses","active"],"columns":["code","type","value","uses_count","max_uses","active"],"order":"code"},
    "faturas":{"model":"billing.Invoice","title":"Faturas","fields":[],"columns":["number","tenant","amount","status","due_at","paid_at"],"order":"-created_at","create":False,"edit":False},
    "pagamentos":{"model":"billing.Payment","title":"Pagamentos","fields":[],"columns":["tenant","purpose","provider","amount","status","due_at","paid_at"],"order":"-created_at","create":False,"edit":False},
    "pix":{"model":"billing.PixCharge","title":"Cobranças Pix","fields":[],"columns":["public_id","tenant","amount","status","expires_at","paid_at"],"order":"-created_at","create":False,"edit":False},
    "eventos-provedor":{"model":"billing.ProviderEvent","title":"Eventos de provedores","fields":[],"columns":["provider","event_type","status","received_at","processed_at"],"order":"-received_at","create":False,"edit":False},
    "conexoes-pagamento":{"model":"billing.TenantPaymentConnection","title":"Conexões de pagamento","fields":[],"columns":["tenant","provider","display_name","environment","status","last_tested_at","last_sync_at"],"order":"tenant__name,provider","create":False,"edit":False},
    "transacoes-pagamento":{"model":"billing.TenantPaymentTransaction","title":"Transações dos estabelecimentos","fields":[],"columns":["tenant","reference_type","method","gross_amount","net_amount","status","paid_at"],"order":"-created_at","create":False,"edit":False},
    "recorrencias-pagamento":{"model":"billing.TenantRecurringSubscription","title":"Recorrências de pagamento","fields":[],"columns":["tenant","reference_type","amount","cycle_months","status","last_payment_at"],"order":"-created_at","create":False,"edit":False},
    "login-audit":{"model":"accounts.LoginAudit","title":"Auditoria de login","fields":[],"columns":["user","email_attempted","event_type","result","ip_address","created_at"],"order":"-created_at","create":False,"edit":False},
    "eventos-seguranca":{"model":"accounts.SecurityEvent","title":"Eventos de segurança","fields":[],"columns":["tenant","user","event_type","severity","ip_address","created_at"],"order":"-created_at","create":False,"edit":False},
    "bloqueios-usuarios":{"model":"accounts.UserBlock","title":"Bloqueios de usuários","fields":[],"columns":["user","reason_code","reason_text","blocked_at","expires_at","unblocked_at"],"order":"-blocked_at","create":False,"edit":False},
    "onboarding":{"model":"tenants.TenantOnboarding","title":"Onboarding das empresas","fields":[],"columns":["tenant","company_done","branding_done","unit_done","professional_done","service_done","schedule_done","email_verification_waived_at","completed_at"],"order":"tenant__name","create":False,"edit":False},
    "historico-empresas":{"model":"tenants.TenantStatusHistory","title":"Histórico das empresas","fields":[],"columns":["tenant","from_status","to_status","reason","changed_by","created_at"],"order":"-created_at","create":False,"edit":False},
    "acessos-suporte":{"model":"operations.SupportAccessSession","title":"Acessos remotos de suporte","fields":[],"columns":["ticket","tenant","master_user","started_at","ended_at"],"order":"-started_at","create":False,"edit":False},
    "verificacoes-backup":{"model":"operations.BackupVerification","title":"Verificações de backup","fields":[],"columns":["backup","status","verification_type","verified_at"],"order":"-verified_at","create":False,"edit":False},
    "alertas-cron":{"model":"operations.CronAlertLog","title":"Alertas dos jobs","fields":[],"columns":["alert_key","channel","status","message","created_at"],"order":"-created_at","create":False,"edit":False},
    "solicitacoes-billing":{"model":"operations.BillingSupportRequest","title":"Solicitações financeiras e exclusões","fields":[],"columns":["tenant","request_type","status","created_at"],"order":"-created_at","create":False,"edit":False},
    "configuracoes-plataforma":{"model":"operations.PlatformSetting","title":"Configurações da plataforma","fields":[],"columns":["tenant","key","is_secret","updated_at"],"order":"key","create":False,"edit":False},
    "blog":{"model":"contenthub.BlogPost","title":"Blog","fields":["slug","title","excerpt","content","cover","status","featured","meta_title","meta_description","published_at"],"columns":["title","slug","status","published_at"],"order":"-published_at,-created_at","special":"blog"},
    "landings":{"model":"contenthub.LandingPage","title":"Landing pages","fields":["slug","locale","segment","headline","subheadline","body","cta_label","cta_url","seo_title","seo_description","active"],"columns":["headline","slug","locale","segment","active","updated_at"],"order":"headline"},
    "avaliacoes-publicas":{"model":"contenthub.PublicReview","title":"Avaliações públicas","fields":["tenant","customer_name","rating","comment","active"],"columns":["tenant","customer_name","rating","active","created_at"],"order":"-created_at"},
    "faq":{"model":"contenthub.FAQItem","title":"FAQ da página inicial","fields":["question","answer","sort_order","active"],"columns":["question","sort_order","active","updated_at"],"order":"sort_order,id"},
    "marketing-contatos":{"model":"communications.MarketingLead","title":"Contatos de e-mail marketing","fields":["name","email","status","source"],"columns":["name","email","status","source","created_at"],"order":"-created_at"},
    "marketing-campanhas":{"model":"communications.MarketingCampaign","title":"Campanhas de e-mail","fields":[],"columns":["subject","status","total_count","sent_count","failed_count","created_at"],"order":"-created_at","create":False,"edit":False},
    "marketing-entregas":{"model":"communications.MarketingDelivery","title":"Entregas de e-mail","fields":[],"columns":["campaign","lead","status","sent_at","opened_at","clicked_at"],"order":"-created_at","create":False,"edit":False},
    "whatsapp-conversas":{"model":"communications.WhatsAppConversation","title":"Conversas WhatsApp","fields":[],"columns":["tenant","contact_name","wa_id","status","assigned_to","last_message_at"],"order":"-last_message_at","create":False,"edit":False},
    "aquisicao":{"model":"growth.AcquisitionEvent","title":"Eventos de aquisição","fields":[],"columns":["event_name","tenant","source","medium","campaign","value_amount","created_at"],"order":"-created_at","create":False,"edit":False},
    "campanhas-indicacao":{"model":"engagement.ReferralIncentiveCampaign","title":"Campanhas Indique e ganhe","fields":["name","active","reward_type","reward_value","company_referrals_enabled","professional_referrals_enabled","starts_at","ends_at"],"columns":["name","reward_type","reward_value","active","starts_at","ends_at"],"order":"-created_at"},
    "recompensas-indicacao":{"model":"engagement.ReferralReward","title":"Recompensas de indicação","fields":[],"columns":["campaign","referrer_user","referred_tenant","referrer_kind","qualified_payment_count","reward_amount","status","pix_key","created_at"],"order":"-created_at","create":False,"edit":False},
    "contas-bancarias":{"model":"billing.TenantBankAccount","title":"Contas bancárias das empresas","fields":[],"columns":["tenant","bank_name","holder_name","account_last4","pix_key_last4","is_primary","active","created_at"],"order":"tenant__name,-is_primary,bank_name","create":False,"edit":False},
    "meta-conversoes":{"model":"growth.MetaConversionLog","title":"Meta Conversions API","fields":[],"columns":["event_name","status","created_at"],"order":"-created_at","create":False,"edit":False},
    "usuarios":{"model":"accounts.User","title":"Usuários","fields":["tenant","email","role","is_active","is_staff"],"columns":["email","tenant","role","is_active","is_staff"],"order":"email"},
    "papeis-usuarios":{"model":"accounts.UserRole","title":"Papéis dos usuários","fields":["user","role"],"columns":["user","role"],"order":"user__email"},
}


def _guard(user):
    if not user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")


class PlatformPaymentForm(forms.Form):
    environment=forms.ChoiceField(choices=PaymentGateway.Environment.choices,label="Ambiente")
    public_key=forms.CharField(max_length=190,required=False,label="Public Key")
    access_token=forms.CharField(label="Access Token",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))
    webhook_secret=forms.CharField(min_length=16,label="Chave secreta do webhook",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))


@login_required
def platform_payment_gateway(request):
    _guard(request.user)
    webhook_url=request.build_absolute_uri("/webhooks/mercadopago/")
    form=PlatformPaymentForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        try:
            configure_mercadopago_gateway(
                environment=form.cleaned_data["environment"],
                public_key=form.cleaned_data["public_key"],
                access_token=form.cleaned_data["access_token"],
                webhook_secret=form.cleaned_data["webhook_secret"],
                webhook_url=webhook_url,
            )
        except (ValueError,RuntimeError,RequestException):
            # Do not echo secrets or provider responses in the Master interface.
            form.add_error(None,"Não foi possível validar a conexão. Confira o ambiente, as credenciais, a chave do webhook e o HTTPS.")
        else:
            messages.success(request,"Provedor de cobrança da plataforma validado e ativado.")
            return redirect("master-platform-payment")
    rows=PaymentGateway.objects.filter(provider="mercadopago").order_by("environment")
    connected=rows.filter(active=True,last_test_status=PaymentGateway.TestStatus.VALIDATED).exists()
    return render(request,"master/platform_payment.html",{
        "form":form,"gateways":rows,"webhook_url":webhook_url,
        "connected":connected,"show_form":not connected or request.GET.get("alterar")=="1" or bool(form.errors),
    })


from communications.master_whatsapp import (  # noqa: E402
    master_whatsapp_inbox,master_whatsapp_status,master_whatsapp_connect,
    master_whatsapp_disconnect,master_whatsapp_receive,master_whatsapp_conversation,
)


def _field(model,name):
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _config(slug):
    config=MASTER_RESOURCES.get(slug)
    if not config:
        raise PermissionDenied
    return config,apps.get_model(config["model"])


def _widgets(model,fields):
    result={}
    for name in fields:
        field=_field(model,name)
        if not field:
            continue
        kind=field.get_internal_type()
        if kind=="DateTimeField":
            result[name]=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M")
        elif kind=="DateField":
            result[name]=forms.DateInput(attrs={"type":"date"})
        elif kind=="TextField":
            result[name]=forms.Textarea(attrs={"rows":4})
    return result


def _value(obj,name):
    if name=="pix_key" and obj._meta.label_lower=="engagement.referralreward":
        if not obj.pix_key_encrypted:
            return "—"
        try:
            from core.crypto import decrypt_text
            return decrypt_text(obj.pix_key_encrypted)
        except Exception:
            return "Indisponível"
    if name=="role" and obj._meta.label_lower=="accounts.user":
        return {"owner":"Responsável","professional":"Profissional","user":"Usuário",
                "master":"Master","manager":"Gestor","staff":"Equipe"}.get(obj.role,obj.role)
    getter=getattr(obj,f"get_{name}_display",None)
    if getter:
        try:return getter()
        except Exception:pass
    value=getattr(obj,name,None)
    if value in (None,""): return "—"
    if isinstance(value,bool): return "Sim" if value else "Não"
    if hasattr(value,"strftime"):
        try:
            value=timezone.localtime(value) if timezone.is_aware(value) else value
            return value.strftime("%d/%m/%Y %H:%M")
        except Exception: return str(value)
    return str(value)


@login_required
def home(request):
    _guard(request.user)
    cards=[{"slug":slug,"title":cfg["title"],"count":(
        apps.get_model(cfg["model"]).objects.filter(deleted_at__isnull=True).count()
        if slug=="usuarios" else apps.get_model(cfg["model"]).objects.count()
    )} for slug,cfg in MASTER_RESOURCES.items()]
    sections=[
        ("Vendas e planos",{"planos","modulos","solicitacoes-modulos","assinaturas","addons-modulos","ajustes-modulos","isencoes-assinaturas","historico-assinaturas","checkouts","cupons","faturas","pagamentos","pix","eventos-provedor","conexoes-pagamento","transacoes-pagamento","recorrencias-pagamento","contas-bancarias"}),
        ("Empresas e pessoas",{"empresas","usuarios","papeis-usuarios","onboarding","historico-empresas","acessos-suporte"}),
        ("Comercial e comunicação",{"equipe-comercial","comerciais","comissoes-comerciais","leads","propostas","campanhas-indicacao","recompensas-indicacao","marketing-contatos","marketing-campanhas","marketing-entregas","whatsapp-conversas","blog","landings","avaliacoes-publicas","faq","aquisicao","meta-conversoes"}),
        ("Suporte e operação",{"suporte","incidentes","backups","homologacao","crons","imports","operacao","alertas-cron","verificacoes-backup","solicitacoes-billing"}),
    ]
    assigned=set().union(*(slugs for _,slugs in sections))
    grouped=[{"title":title,"cards":[card for card in cards if card["slug"] in slugs]} for title,slugs in sections]
    grouped.append({"title":"Auditoria e configurações","cards":[card for card in cards if card["slug"] not in assigned]})
    return render(request,"master/home.html",{
        "cards":cards,"groups":grouped,
        "public_plans":Plan.objects.filter(active=True,public_visible=True,is_custom=False).count(),
        "active_modules":Module.objects.filter(active=True).count(),
    })


@login_required
def tenant_access(request,pk):
    from accounts.models import User
    from billing.entitlements import module_enabled
    from billing.models import TenantModule
    from communications.models import Notification
    from legal.middleware import current_documents
    from legal.models import LegalAcceptance,LegalDocument
    from tenants.models import Tenant
    _guard(request.user)
    tenant=get_object_or_404(Tenant,pk=pk,deleted_at__isnull=True)
    modules=list(Module.objects.filter(active=True).order_by("sort_order","name"))
    if request.method=="POST":
        selected={int(value) for value in request.POST.getlist("modules") if value.isdigit()}
        with transaction.atomic():
            for item in modules:
                TenantModule.objects.update_or_create(tenant=tenant,module=item,
                    defaults={"enabled":item.pk in selected})
        messages.success(request,"Acessos da empresa atualizados pelo Master.")
        return redirect("master-tenant-access",pk=tenant.pk)
    terms=next((doc for doc in current_documents() if doc.type==LegalDocument.Type.TERMS),None)
    owners=list(User.objects.filter(tenant=tenant,role="owner",is_active=True).exclude(email="").order_by("email"))
    accepted=dict(LegalAcceptance.objects.filter(document=terms,user__in=owners)
        .values_list("user_id","accepted_at")) if terms else {}
    notices={}
    if terms:
        for notice in Notification.objects.filter(tenant=tenant,channel=Notification.Channel.EMAIL,
            template_key="tenant_terms_acceptance",payload__document_id=terms.pk).order_by("-created_at","-pk"):
            notices.setdefault(notice.destination.lower(),notice)
    return render(request,"master/tenant_access.html",{"tenant":tenant,
        "modules":[{"module":item,"enabled":module_enabled(tenant,item.slug)} for item in modules],
        "terms":terms,"owner_terms":[{"user":owner,"accepted_at":accepted.get(owner.pk),
            "notice":notices.get(owner.email.lower())} for owner in owners]})


@login_required
@require_POST
def send_tenant_terms(request,pk):
    from accounts.models import User
    from communications.models import Notification
    from legal.middleware import current_documents
    from legal.models import LegalAcceptance,LegalDocument
    from tenants.models import Tenant
    _guard(request.user)
    tenant=get_object_or_404(Tenant,pk=pk,deleted_at__isnull=True)
    terms=next((doc for doc in current_documents() if doc.type==LegalDocument.Type.TERMS),None)
    if not terms:
        messages.error(request,"Publique os Termos em Documentos legais antes de enviar o convite.")
    else:
        owners=User.objects.filter(tenant=tenant,role="owner",is_active=True).exclude(email="")
        accepted=set(LegalAcceptance.objects.filter(document=terms,user__in=owners)
            .values_list("user_id",flat=True))
        link=request.build_absolute_uri(reverse("legal-accept"))
        count=0
        for owner in owners:
            if owner.pk in accepted:
                continue
            Notification.objects.create(tenant=tenant,channel=Notification.Channel.EMAIL,
                destination=owner.email,template_key="tenant_terms_acceptance",
                payload={"subject":"Aceite de termos do ApPlanner",
                    "text":f"Olá! Os Termos de Uso do ApPlanner (versão {terms.version}) aguardam seu aceite. Entre com sua conta e aceite os documentos para continuar usando {tenant.name}: {link}",
                    "document_id":terms.pk,"user_id":owner.pk})
            count+=1
        if count:
            messages.success(request,f"{count} convite(s) colocado(s) na fila de e-mail. Acompanhe a situação abaixo.")
        elif owners.exists():
            messages.info(request,"Todos os responsáveis ativos já aceitaram a versão atual dos termos.")
        else:
            messages.error(request,"Cadastre um responsável ativo com e-mail antes de enviar os termos.")
    return redirect("master-tenant-access",pk=tenant.pk)


class ChatbotMasterForm(forms.Form):
    tenant=forms.ModelChoiceField(queryset=None,label="Estabelecimento")
    phone_number_id=forms.CharField(max_length=100,required=False,label="ID do número na WhatsApp Cloud API")
    enabled=forms.BooleanField(required=False,label="Ativar respostas automáticas")
    greeting=forms.CharField(max_length=1000,label="Mensagem inicial",widget=forms.Textarea(attrs={"rows":3}))
    fallback=forms.CharField(max_length=1000,label="Mensagem antes do atendimento humano",widget=forms.Textarea(attrs={"rows":3}))
    handoff=forms.CharField(max_length=1000,label="Mensagem de transferência",widget=forms.Textarea(attrs={"rows":3}))
    rules_text=forms.CharField(required=False,label="Respostas por assunto",widget=forms.Textarea(attrs={"rows":8,"placeholder":"horário;funcionamento | Nosso horário de atendimento é..."}))

    def __init__(self,*args,**kwargs):
        from tenants.models import Tenant
        super().__init__(*args,**kwargs)
        self.fields["tenant"].queryset=Tenant.objects.filter(deleted_at__isnull=True).order_by("name")

    def clean_rules_text(self):
        lines=(self.cleaned_data["rules_text"] or "").splitlines()
        if len(lines)>20:
            raise forms.ValidationError("Cadastre até 20 respostas.")
        result=[]
        for line in lines:
            if not line.strip():
                continue
            keywords,separator,reply=line.partition("|")
            triggers=[part.strip() for part in keywords.split(";") if part.strip()]
            if not separator or not triggers or not reply.strip() or len(reply.strip())>1000 or any(len(trigger)>80 for trigger in triggers):
                raise forms.ValidationError("Use uma linha por resposta: palavra;outra palavra | texto da resposta (até 1.000 caracteres).")
            result.append({"keywords":triggers,"reply":reply.strip()})
        return result


@login_required
def chatbot_flow(request):
    from communications.models import ChatbotFlow
    from django.conf import settings
    from tenants.models import Tenant

    _guard(request.user)
    selected_id=request.POST.get("tenant") if request.method=="POST" else request.GET.get("tenant")
    flow=ChatbotFlow.objects.filter(tenant_id=selected_id).select_related("tenant").first() if selected_id and str(selected_id).isdigit() else None
    initial={"tenant":selected_id,"greeting":"Olá! Como podemos ajudar?", "fallback":"Vou encaminhar você para nossa equipe.","handoff":"Vou chamar um atendente para ajudar você."}
    if flow:
        initial.update({"enabled":flow.enabled,"greeting":flow.greeting,"fallback":flow.fallback,"handoff":flow.handoff,
                        "rules_text":"\n".join(";".join(rule.get("keywords",[]))+" | "+rule.get("reply","") for rule in flow.rules)})
        initial["phone_number_id"]=(flow.tenant.metadata or {}).get("whatsapp_phone_number_id","")
    elif selected_id and str(selected_id).isdigit():
        tenant=Tenant.objects.filter(pk=selected_id).first()
        if tenant:
            initial["phone_number_id"]=(tenant.metadata or {}).get("whatsapp_phone_number_id","")
    form=ChatbotMasterForm(request.POST or None,initial=initial)
    if request.method=="POST" and form.is_valid():
        data=form.cleaned_data
        if data["phone_number_id"] and Tenant.objects.filter(
            metadata__whatsapp_phone_number_id=data["phone_number_id"],deleted_at__isnull=True,
        ).exclude(pk=data["tenant"].pk).exists():
            form.add_error("phone_number_id","Esse número já está vinculado a outra empresa.")
        if data["enabled"] and not (
            settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID
            and settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_VERIFY_TOKEN
            and data["phone_number_id"]==settings.WHATSAPP_PHONE_NUMBER_ID
        ):
            form.add_error("enabled","Configure a Cloud API no servidor e vincule o número ao estabelecimento antes de ativar.")
    if request.method=="POST" and form.is_valid() and not form.errors:
        data=form.cleaned_data
        if data["phone_number_id"]:
            tenant=data["tenant"]
            tenant.metadata={**(tenant.metadata or {}),"whatsapp_phone_number_id":data["phone_number_id"]}
            tenant.save(update_fields=["metadata","updated_at"])
        ChatbotFlow.objects.update_or_create(tenant=data["tenant"],defaults={
            "enabled":data["enabled"],"greeting":data["greeting"],
            "fallback":data["fallback"],"handoff":data["handoff"],"rules":data["rules_text"],
        })
        messages.success(request,"Fluxo do chatbot salvo.")
        return redirect(f"{request.path}?tenant={data['tenant'].pk}")
    return render(request,"master/chatbot.html",{"form":form,"flow":flow,
        "whatsapp_configured":bool(settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_APP_SECRET and settings.WHATSAPP_VERIFY_TOKEN),
        "phone_number_id":settings.WHATSAPP_PHONE_NUMBER_ID})


@login_required
def resource_list(request,slug):
    _guard(request.user)
    config,model=_config(slug)
    qs=model.objects.filter(deleted_at__isnull=True) if slug=="usuarios" else model.objects.all()
    q=(request.GET.get("q") or "").strip()
    if q:
        lookup=Q()
        for f in model._meta.fields:
            if f.get_internal_type() in {"CharField","TextField","EmailField","SlugField"}:
                lookup|=Q(**{f"{f.name}__icontains":q})
        qs=qs.filter(lookup)
    order=config.get("order")
    if order: qs=qs.order_by(*[x.strip() for x in order.split(",")])
    columns=config["columns"]
    headers=[FIELD_LABELS.get(c) or field_label(model,c) for c in columns]
    rows=[{"obj":obj,"cells":[_value(obj,c) for c in columns]} for obj in qs[:300]]
    help_text={
        "planos":"Para publicar um plano, marque Ativo e Visível ao público. Use Módulos em cada plano para escolher as funções; preços e dias de teste são editados no próprio plano.",
        "empresas":"Para aparecer no diretório, a empresa precisa estar ativa ou em teste, com Página pública ligada. Informe cidade e latitude/longitude da unidade para ordenar por proximidade.",
        "solicitacoes-modulos":"Solicitações de contratação são abertas pela empresa e analisadas aqui. Para liberar o WhatsApp de uma empresa, selecione-a no painel Operação e use Conectar WhatsApp da empresa.",
        "solicitacoes-billing":"Pedidos de exclusão podem ser concluídos aqui. Aprovar e excluir desativa a página pública, encerra os acessos dos usuários, cancela a assinatura ativa e envia a confirmação por e-mail ao solicitante.",
    }
    return render(request,"master/list.html",{"slug":slug,"resource":config,"headers":headers,"rows":rows,"q":q,"help_text":help_text.get(slug)})


@login_required
def resource_form(request,slug,pk=None):
    _guard(request.user)
    config,model=_config(slug)
    if slug=="solicitacoes-modulos" and pk is None:
        messages.info(request,"Para liberar o WhatsApp, selecione a empresa em Operação e abra Conectar WhatsApp da empresa. Solicitações de contratação são abertas pela própria empresa.")
        from django.urls import reverse
        from tenants.models import Tenant
        selected=request.session.get("portal_tenant_id")
        if selected and Tenant.objects.filter(pk=selected).exists():
            return redirect("tenant-whatsapp-settings")
        return redirect("portal-home")
    if pk is None and not config.get("create",True): raise PermissionDenied
    if pk is not None and not config.get("edit",True): raise PermissionDenied
    obj=get_object_or_404(model,pk=pk,deleted_at__isnull=True) if pk and slug=="usuarios" else (get_object_or_404(model,pk=pk) if pk else None)
    Form=(UserMasterForm if slug=="usuarios" else TenantMasterForm if slug=="empresas" else PlanMasterForm if config.get("special")=="plan"
          else modelform_factory(model,fields=config["fields"],widgets=_widgets(model,config["fields"])))
    form=Form(request.POST or None,request.FILES or None,instance=obj)
    for name,field in form.fields.items():
        if name not in {"new_password","confirm_password"}:
            field.label=FIELD_LABELS.get(name) or field_label(model,name)
    if slug=="assinaturas":
        form.fields["provider_environment"].widget=forms.Select(choices=[
            ("","Não identificado"),("sandbox","Teste"),("production","Produção"),
        ])
    for name,field in form.fields.items():
        mf=_field(model,name)
        if mf and mf.get_internal_type()=="DateTimeField":
            field.input_formats=["%Y-%m-%dT%H:%M","%Y-%m-%d %H:%M:%S"]
    if request.method=="POST" and form.is_valid():
        row=form.save(commit=False)
        if config.get("special")=="platform_finance" and not row.created_by_id:
            row.created_by=request.user
        if config.get("special")=="plan" and row.is_custom and not row.created_by_id:
            row.created_by=request.user
        if config.get("special")=="operation_settings":
            row.updated_by=request.user
        if config.get("special")=="subscription_exemption" and not row.granted_by_id:
            row.granted_by=request.user
        if config.get("special")=="blog" and not row.author_id:
            row.author=request.user
        try:
            row.full_clean()
            row.save()
            form.save_m2m()
            messages.success(request,"Registro salvo.")
            return redirect("master-resource-list",slug=slug)
        except ValidationError as exc:
            # Some model constraints involve fields intentionally absent from
            # the Master form. Report them instead of raising a second error.
            if hasattr(exc,"message_dict"):
                for field,errors in exc.message_dict.items():
                    for error in errors:
                        form.add_error(field if field in form.fields else None,error)
            else:
                form.add_error(None,exc)
    return render(request,"master/form.html",{"slug":slug,"resource":config,"form":form,"title":("Editar" if obj else "Novo")+" — "+config["title"]})


@login_required
def remove_user(request,pk):
    """Revoga o acesso sem apagar registros financeiros, clínicos ou de auditoria."""
    _guard(request.user)
    from accounts.models import SecurityEvent,User

    user=get_object_or_404(User.objects.select_related("tenant"),pk=pk,deleted_at__isnull=True)
    if user.pk==request.user.pk:
        raise PermissionDenied("Você não pode excluir sua própria conta Master.")
    if request.method=="POST":
        if request.POST.get("confirm_email","").strip().lower()!=user.email.lower():
            messages.error(request,"Digite o e-mail exato do usuário para confirmar a exclusão.")
        else:
            with transaction.atomic():
                user=User.objects.select_for_update().get(pk=pk,deleted_at__isnull=True)
                old_role=user.role
                user.is_active=False
                user.is_staff=False
                user.is_superuser=False
                user.role="deleted"
                user.email=f"excluido-{user.pk}@users.invalid"
                user.first_name=""
                user.last_name=""
                user.email_verified_at=None
                user.two_factor_secret_encrypted=""
                user.two_factor_enabled_at=None
                user.must_change_password=False
                user.session_version+=1
                user.deleted_at=timezone.now()
                user.set_unusable_password()
                user.save()
                user.groups.clear()
                user.user_permissions.clear()
                user.role_links.all().delete()
                user.api_tokens.all().delete()
                user.trusted_devices.all().delete()
                user.recovery_codes.all().delete()
                user.email_verification_tokens.all().delete()
                user.password_reset_tokens.all().delete()
                SecurityEvent.objects.create(
                    user=request.user,tenant=user.tenant,event_type="master_user_removed",
                    severity=SecurityEvent.Severity.HIGH,
                    metadata={"removed_user_id":user.pk,"previous_role":old_role},
                )
            messages.success(request,"Acesso excluído. O histórico operacional foi preservado.")
            return redirect("master-resource-list",slug="usuarios")
    return render(request,"master/user_remove.html",{"target":user})


def _plan_references(plan):
    from billing.models import CheckoutSession,Subscription,SubscriptionHistory
    from commercial.models import Proposal
    references=[]
    if Subscription.objects.filter(plan=plan).exists(): references.append("assinaturas, inclusive históricas")
    if CheckoutSession.objects.filter(plan=plan).exists(): references.append("checkouts ou tentativas de pagamento")
    if Proposal.objects.filter(Q(plan=plan)|Q(base_plan=plan)).exists(): references.append("propostas comerciais")
    if SubscriptionHistory.objects.filter(Q(from_plan=plan)|Q(to_plan=plan)).exists():
        references.append("histórico de trocas de plano")
    return references


@login_required
def delete_plan(request,pk):
    """Remove somente planos sem vínculos, preservando o histórico comercial."""
    _guard(request.user)
    plan=get_object_or_404(Plan,pk=pk)
    references=_plan_references(plan)
    if request.method=="POST":
        if references:
            messages.error(request,"Este plano não pode ser excluído porque possui "+", ".join(references)+". Desative a venda e deixe-o invisível para preservar o histórico.")
            return redirect("master-resource-list",slug="planos")
        if request.POST.get("confirm_name","").strip()!=plan.name:
            messages.error(request,"Digite o nome exato do plano para confirmar a exclusão.")
        else:
            try:
                with transaction.atomic():
                    locked=Plan.objects.select_for_update().get(pk=plan.pk)
                    if _plan_references(locked):
                        raise ValidationError("O plano recebeu novos vínculos e não pode ser excluído. Desative-o para preservar o histórico.")
                    locked.delete()
            except (ProtectedError,ValidationError):
                messages.error(request,"O plano recebeu vínculos e não pode ser excluído. Desative-o para preservar o histórico.")
                return redirect("master-resource-list",slug="planos")
            messages.success(request,f"Plano {plan.name} excluído.")
            return redirect("master-resource-list",slug="planos")
    return render(request,"master/plan_delete.html",{"plan":plan,"references":references})


def _approve_account_deletion(row,actor):
    """Encerra a operação da empresa preservando somente registros necessários para auditoria."""
    from accounts.models import SecurityEvent,User
    from applanner.transactional_email import queue_email
    from billing.models import PaymentGateway,Subscription,SubscriptionHistory
    from billing.payment_services import platform_provider
    from core.models import AuditLog
    from operations.models import BillingSupportRequest,SupportTicket
    from tenants.models import Tenant

    with transaction.atomic():
        row=(BillingSupportRequest.objects.select_for_update()
             .select_related("tenant","user","ticket").get(pk=row.pk))
        if row.request_type!=BillingSupportRequest.RequestType.ACCOUNT_DELETION:
            raise ValidationError("Esta solicitação não é de exclusão de conta.")
        if row.status!=BillingSupportRequest.Status.PENDING:
            raise ValidationError("Esta solicitação já foi analisada.")

        tenant=Tenant.objects.select_for_update().get(pk=row.tenant_id)
        requester_email=row.user.email
        requester_name=row.user.first_name or requester_email.split("@")[0]
        company_name=tenant.name
        previous_tenant_status=tenant.status
        now=timezone.now()

        subscriptions=list(
            Subscription.objects.select_for_update().filter(tenant=tenant)
            .exclude(status=Subscription.Status.CANCELLED).select_related("plan")
            .order_by("-started_at")
        )
        for subscription in subscriptions:
            if subscription.provider_subscription_id:
                gateway_qs=PaymentGateway.objects.filter(
                    provider="mercadopago",active=True,
                    last_test_status=PaymentGateway.TestStatus.VALIDATED,
                )
                if subscription.provider_environment:
                    gateway_qs=gateway_qs.filter(environment=subscription.provider_environment)
                gateway=gateway_qs.first()
                if not gateway:
                    raise ValidationError(
                        "Não foi possível excluir a conta porque a assinatura recorrente ainda "
                        "não pôde ser cancelada no provedor de cobrança."
                    )
                remote=platform_provider(gateway).cancel_subscription(subscription.provider_subscription_id)
                if remote.get("status") not in {"canceled","cancelled"}:
                    raise ValidationError(
                        "O provedor de cobrança não confirmou o cancelamento da assinatura. "
                        "A exclusão não foi executada."
                    )
            previous=subscription.status
            subscription.status=Subscription.Status.CANCELLED
            subscription.cancelled_at=now
            subscription.next_billing_at=None
            subscription.provider_checkout_url=""
            subscription.save(update_fields=[
                "status","cancelled_at","next_billing_at","provider_checkout_url","updated_at",
            ])
            SubscriptionHistory.objects.create(
                subscription=subscription,tenant=tenant,
                from_plan=subscription.plan,to_plan=subscription.plan,
                from_status=previous,to_status=subscription.status,
                reason="Exclusão da conta aprovada pelo Master",
            )

        queue_email(
            tenant,requester_email,"account_deletion_approved",
            {"nome":requester_name,"empresa":company_name},
        )

        tenant.status=Tenant.Status.CANCELLED
        tenant.public_enabled=False
        tenant.public_booking_enabled=False
        tenant.deleted_at=now
        tenant.slug=(f"excluido-{tenant.pk}-{tenant.slug}")[:120]
        tenant.public_slug=None
        tenant.public_short_code=None
        tenant.document=""
        tenant.email=""
        tenant.phone=""
        tenant.description=""
        tenant.metadata={}
        tenant.save(update_fields=[
            "status","public_enabled","public_booking_enabled","deleted_at","slug",
            "public_slug","public_short_code","document","email","phone","description",
            "metadata","updated_at",
        ])

        tenant_users=list(User.objects.select_for_update().filter(tenant=tenant,deleted_at__isnull=True))
        removed_user_ids=[]
        for user in tenant_users:
            removed_user_ids.append(user.pk)
            old_role=user.role
            user.is_active=False
            user.is_staff=False
            user.is_superuser=False
            user.role="deleted"
            user.email=f"excluido-{user.pk}@users.invalid"
            user.first_name=""
            user.last_name=""
            user.email_verified_at=None
            user.two_factor_secret_encrypted=""
            user.two_factor_enabled_at=None
            user.must_change_password=False
            user.session_version+=1
            user.deleted_at=now
            user.set_unusable_password()
            user.save()
            user.groups.clear()
            user.user_permissions.clear()
            user.role_links.all().delete()
            user.api_tokens.all().delete()
            user.trusted_devices.all().delete()
            user.recovery_codes.all().delete()
            user.email_verification_tokens.all().delete()
            user.password_reset_tokens.all().delete()
            SecurityEvent.objects.create(
                user=actor,tenant=tenant,event_type="master_tenant_user_removed",
                severity=SecurityEvent.Severity.HIGH,
                metadata={"removed_user_id":user.pk,"previous_role":old_role,"deletion_request_id":row.pk},
            )

        row.status=BillingSupportRequest.Status.COMPLETED
        row.reviewed_by=actor
        row.reviewed_at=now
        row.completed_at=now
        row.save(update_fields=["status","reviewed_by","reviewed_at","completed_at","updated_at"])

        row.ticket.status=SupportTicket.Status.CLOSED
        row.ticket.assigned_to=actor
        row.ticket.save(update_fields=["status","assigned_to","updated_at"])

        AuditLog.objects.create(
            tenant=tenant,user=actor,action="MASTER_ACCOUNT_DELETION_APPROVED",
            entity_type="operations.BillingSupportRequest",entity_id=row.pk,
            before={"tenant_status":previous_tenant_status,"request_status":"pending"},
            after={"tenant_status":"cancelled","request_status":"completed","removed_user_ids":removed_user_ids},
        )
        return company_name


@login_required
def operational_action(request,action,pk=None):
    _guard(request.user)
    if request.method!="POST":
        raise PermissionDenied
    from operations.backup import create_database_backup,verify_database_backup
    from operations.models import Backup,OperationalIncident
    from operations.services import run_homologation
    from billing.models import ModuleRequest
    from billing.module_services import activate_module_request,review_module_request

    try:
        if action=="backup-create":
            backup=create_database_backup()
            messages.success(request,f"Backup #{backup.pk} concluído.")
            return redirect("master-resource-list",slug="backups")
        if action=="backup-verify":
            backup=get_object_or_404(Backup,pk=pk)
            verification=verify_database_backup(backup=backup,user=request.user)
            if verification.status=="passed":
                messages.success(request,"Integridade do backup confirmada.")
            else:
                messages.error(request,"Falha na verificação do backup.")
            return redirect("master-resource-list",slug="backups")
        if action in {"account-deletion-approve","account-deletion-reject"}:
            from operations.models import BillingSupportRequest,SupportTicket
            row=get_object_or_404(BillingSupportRequest,pk=pk)
            if row.request_type!=BillingSupportRequest.RequestType.ACCOUNT_DELETION:
                raise ValidationError("Esta solicitação não é de exclusão de conta.")
            if row.status!=BillingSupportRequest.Status.PENDING:
                raise ValidationError("Esta solicitação já foi analisada.")
            if action=="account-deletion-reject":
                now=timezone.now()
                with transaction.atomic():
                    row=BillingSupportRequest.objects.select_for_update().select_related("ticket").get(pk=row.pk)
                    if row.status!=BillingSupportRequest.Status.PENDING:
                        raise ValidationError("Esta solicitação já foi analisada.")
                    row.status=BillingSupportRequest.Status.REJECTED
                    row.reviewed_by=request.user
                    row.reviewed_at=now
                    row.save(update_fields=["status","reviewed_by","reviewed_at","updated_at"])
                    row.ticket.status=SupportTicket.Status.RESOLVED
                    row.ticket.assigned_to=request.user
                    row.ticket.save(update_fields=["status","assigned_to","updated_at"])
                messages.success(request,"Solicitação de exclusão rejeitada.")
            else:
                company_name=_approve_account_deletion(row,request.user)
                messages.success(request,f"Conta de {company_name} excluída e e-mail de confirmação colocado na fila.")
            return redirect("master-resource-list",slug="solicitacoes-billing")
        if action=="referral-reward-paid":
            from engagement.models import ReferralReward
            row=get_object_or_404(
                ReferralReward,pk=pk,status=ReferralReward.Status.READY,
                referrer_kind=ReferralReward.ReferrerKind.PROFESSIONAL,
            )
            row.status=ReferralReward.Status.PAID
            row.paid_at=timezone.now()
            row.save(update_fields=["status","paid_at","updated_at"])
            messages.success(request,"Recompensa marcada como paga ao profissional.")
            return redirect("master-resource-list",slug="recompensas-indicacao")
        if action in {"module-request-approve","module-request-reject"}:
            row=get_object_or_404(ModuleRequest,pk=pk)
            approved=action=="module-request-approve"
            if row.status==ModuleRequest.Status.PENDING:
                review_module_request(
                    module_request=row,user=request.user,approved=approved,
                    note=request.POST.get("note",""),
                )
            elif not approved or row.status not in {
                ModuleRequest.Status.APPROVED,ModuleRequest.Status.PAYMENT_FAILED,
            }:
                raise ValidationError("Esta solicitação não está disponível para aprovação.")
            if approved:
                adjustment=activate_module_request(module_request=row,user=request.user)
                if adjustment.status==adjustment.Status.APPLIED:
                    messages.success(request,
                        f"Módulo ativado. Novo valor da assinatura: R$ {adjustment.new_amount:.2f} por ciclo.")
                else:
                    messages.error(request,
                        "O provedor de cobrança não confirmou a alteração. O módulo permanece bloqueado "
                        "e o valor da assinatura não mudou. Confira a conexão e tente novamente. "
                        +adjustment.error_code)
            else:
                messages.success(request,"Solicitação de módulo rejeitada.")
            return redirect("master-resource-list",slug="solicitacoes-modulos")
        if action=="homologation-run":
            run=run_homologation(user=request.user)
            messages.success(request,f"Homologação executada: {run.get_status_display()} · {run.score}.")
            return redirect("master-resource-list",slug="homologacao")
        if action in {"incident-ack","incident-resolve"}:
            incident=get_object_or_404(OperationalIncident,pk=pk)
            now=timezone.now()
            if action=="incident-ack":
                incident.status=OperationalIncident.Status.ACKNOWLEDGED
                incident.acknowledged_by=request.user
                incident.acknowledged_at=now
                incident.save(update_fields=["status","acknowledged_by","acknowledged_at","updated_at"])
                messages.success(request,"Incidente reconhecido.")
            else:
                incident.status=OperationalIncident.Status.RESOLVED
                incident.resolved_by=request.user
                incident.resolved_at=now
                incident.save(update_fields=["status","resolved_by","resolved_at","updated_at"])
                messages.success(request,"Incidente resolvido.")
            return redirect("master-resource-list",slug="incidentes")
    except Exception as exc:
        messages.error(request,f"Falha operacional: {str(exc)[:240]}")
        if action.startswith("account-deletion"):
            return redirect("master-resource-list",slug="solicitacoes-billing")
    return redirect("master-home")


@login_required
def plan_modules(request,pk):
    _guard(request.user)
    plan=get_object_or_404(Plan,pk=pk)
    modules=list(Module.objects.order_by("sort_order","name"))
    current={row.module_id:row.enabled for row in plan.module_links.all()}
    if request.method=="POST":
        selected={int(value) for value in request.POST.getlist("modules") if value.isdigit()}
        for module in modules:
            PlanModule.objects.update_or_create(
                plan=plan,module=module,defaults={"enabled":module.pk in selected}
            )
        messages.success(request,"Módulos do plano atualizados.")
        return redirect("master-plan-modules",pk=plan.pk)
    rows=[{"module":module,"enabled":bool(current.get(module.pk,False))} for module in modules]
    return render(request,"master/plan_modules.html",{"plan":plan,"rows":rows})
