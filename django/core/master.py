from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Q
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from billing.models import Module, Plan, PlanModule


class PlanMasterForm(forms.ModelForm):
    professionals_limit=forms.IntegerField(min_value=1,required=False,label="Limite de profissionais")
    units_limit=forms.IntegerField(min_value=1,required=False,label="Limite de unidades")
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
        features=(getattr(self.instance,"features",None) or {}) if self.instance else {}
        self.fields["professionals_limit"].initial=features.get("professionals")
        self.fields["units_limit"].initial=features.get("units")
        self.fields["included_features"].initial="\n".join(features.get("included_features") or [])

    def save(self,commit=True):
        obj=super().save(commit=False)
        features=dict(obj.features or {})
        if self.cleaned_data.get("professionals_limit"):
            features["professionals"]=self.cleaned_data["professionals_limit"]
        if self.cleaned_data.get("units_limit"):
            features["units"]=self.cleaned_data["units_limit"]
        features["included_features"]=[
            line.strip() for line in (self.cleaned_data.get("included_features") or "").splitlines()
            if line.strip()
        ][:30]
        obj.features=features
        if commit:
            obj.save()
        return obj


MASTER_RESOURCES={
    "empresas":{"model":"tenants.Tenant","title":"Empresas","fields":["name","slug","public_slug","category","email","phone","status","public_enabled","public_booking_enabled","locale","timezone"],"columns":["name","slug","category","status","created_at"],"order":"-created_at"},
    "planos":{"model":"billing.Plan","title":"Planos","fields":["name","slug","description","monthly_price","quarterly_price","semiannual_price","annual_price","trial_days","trial_without_card","active","public_visible","is_custom","featured","sort_order"],"columns":["name","monthly_price","trial_days","active","public_visible","is_custom","featured"],"order":"sort_order,name","special":"plan"},
    "modulos":{"model":"billing.Module","title":"Módulos","fields":["name","slug","description","addon_monthly_price","addon_sellable","sort_order","active"],"columns":["name","slug","addon_monthly_price","addon_sellable","active"],"order":"sort_order,name"},
    "solicitacoes-modulos":{"model":"billing.ModuleRequest","title":"Solicitações de módulos","fields":["tenant","module","quoted_monthly_price","status","tenant_note","master_note"],"columns":["tenant","module","quoted_monthly_price","status","created_at"],"order":"-created_at"},
    "equipe-comercial":{"model":"commercial.CommercialProfile","title":"Equipe comercial","fields":["user","commission_percent","max_discount_percent","support_enabled","active"],"columns":["user","commission_percent","max_discount_percent","support_enabled","active"],"order":"user__email"},
    "comissoes-comerciais":{"model":"commercial.CommercialCommission","title":"Comissões comerciais","fields":["commercial_user","tenant","base_amount","commission_percent","commission_amount","status","hold_until"],"columns":["commercial_user","tenant","commission_amount","status","created_at"],"order":"-created_at"},
    "assinaturas":{"model":"billing.Subscription","title":"Assinaturas","fields":["tenant","plan","billing_cycle","contracted_price","status","started_at","trial_ends_at","next_billing_at","provider_customer_id","provider_subscription_id"],"columns":["tenant","plan","billing_cycle","status","next_billing_at"],"order":"-started_at"},
    "financeiro":{"model":"finance.PlatformFinancialTransaction","title":"Financeiro da plataforma","fields":["category","type","description","amount","status","due_at","paid_at","notes"],"columns":["type","description","amount","status","due_at"],"order":"-created_at","special":"platform_finance"},
    "suporte":{"model":"operations.SupportTicket","title":"Suporte","fields":["tenant","user","category","subject","description","priority","status","assigned_to"],"columns":["protocol","tenant","subject","priority","status","assigned_to"],"order":"-created_at","create":False},
    "incidentes":{"model":"operations.OperationalIncident","title":"Incidentes","fields":["category","severity","title","details","status"],"columns":["severity","title","status","occurrence_count","last_seen_at"],"order":"-last_seen_at","create":False},
    "backups":{"model":"operations.Backup","title":"Backups","fields":[],"columns":["type","scope","status","destination","size_bytes","completed_at"],"order":"-started_at","create":False,"edit":False},
    "homologacao":{"model":"operations.HomologationRun","title":"Homologações","fields":[],"columns":["status","score","executed_by","created_at"],"order":"-created_at","create":False,"edit":False},
    "legais":{"model":"legal.LegalDocument","title":"Documentos legais","fields":["type","version","title","content","status","published_at"],"columns":["type","version","title","status","published_at"],"order":"-published_at,-created_at"},
    "comerciais":{"model":"commercial.CommercialProfile","title":"Equipe comercial","fields":["user","commission_percent","max_discount_percent","support_enabled","active"],"columns":["user","commission_percent","max_discount_percent","support_enabled","active"],"order":"user__email"},
    "comissoes-comerciais":{"model":"commercial.CommercialCommission","title":"Comissões comerciais","fields":[],"columns":["commercial_user","tenant","base_amount","commission_amount","status","paid_at"],"order":"-created_at","create":False,"edit":False},
    "leads":{"model":"commercial.Lead","title":"Leads comerciais","fields":[],"columns":["name","business_type","status","assigned_to","next_contact_at","created_at"],"order":"-created_at","create":False,"edit":False},
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
    "onboarding":{"model":"tenants.TenantOnboarding","title":"Onboarding das empresas","fields":[],"columns":["tenant","company_done","branding_done","unit_done","professional_done","service_done","schedule_done","payment_done","public_page_done","completed_at"],"order":"tenant__name","create":False,"edit":False},
    "historico-empresas":{"model":"tenants.TenantStatusHistory","title":"Histórico das empresas","fields":[],"columns":["tenant","from_status","to_status","reason","changed_by","created_at"],"order":"-created_at","create":False,"edit":False},
    "acessos-suporte":{"model":"operations.SupportAccessSession","title":"Acessos remotos de suporte","fields":[],"columns":["ticket","tenant","master_user","started_at","ended_at"],"order":"-started_at","create":False,"edit":False},
    "verificacoes-backup":{"model":"operations.BackupVerification","title":"Verificações de backup","fields":[],"columns":["backup","status","verification_type","verified_at"],"order":"-verified_at","create":False,"edit":False},
    "alertas-cron":{"model":"operations.CronAlertLog","title":"Alertas dos jobs","fields":[],"columns":["alert_key","channel","status","message","created_at"],"order":"-created_at","create":False,"edit":False},
    "solicitacoes-billing":{"model":"operations.BillingSupportRequest","title":"Solicitações financeiras","fields":[],"columns":["tenant","request_type","status","created_at"],"order":"-created_at","create":False,"edit":False},
    "configuracoes-plataforma":{"model":"operations.PlatformSetting","title":"Configurações da plataforma","fields":[],"columns":["tenant","key","is_secret","updated_at"],"order":"key","create":False,"edit":False},
    "blog":{"model":"contenthub.BlogPost","title":"Blog","fields":["slug","title","excerpt","content","status","featured","meta_title","meta_description","published_at"],"columns":["title","slug","status","published_at"],"order":"-published_at,-created_at","special":"blog"},
    "landings":{"model":"contenthub.LandingPage","title":"Landing pages","fields":["slug","locale","segment","headline","subheadline","body","cta_label","cta_url","seo_title","seo_description","active"],"columns":["headline","slug","locale","segment","active","updated_at"],"order":"headline"},
    "avaliacoes-publicas":{"model":"contenthub.PublicReview","title":"Avaliações públicas","fields":["tenant","customer_name","rating","comment","active"],"columns":["tenant","customer_name","rating","active","created_at"],"order":"-created_at"},
    "marketing-contatos":{"model":"communications.MarketingLead","title":"Contatos de e-mail marketing","fields":["name","email","status","source"],"columns":["name","email","status","source","created_at"],"order":"-created_at"},
    "marketing-campanhas":{"model":"communications.MarketingCampaign","title":"Campanhas de e-mail","fields":[],"columns":["subject","status","total_count","sent_count","failed_count","created_at"],"order":"-created_at","create":False,"edit":False},
    "marketing-entregas":{"model":"communications.MarketingDelivery","title":"Entregas de e-mail","fields":[],"columns":["campaign","lead","status","sent_at","opened_at","clicked_at"],"order":"-created_at","create":False,"edit":False},
    "whatsapp-conversas":{"model":"communications.WhatsAppConversation","title":"Conversas WhatsApp","fields":[],"columns":["tenant","contact_name","wa_id","status","assigned_to","last_message_at"],"order":"-last_message_at","create":False,"edit":False},
    "aquisicao":{"model":"growth.AcquisitionEvent","title":"Eventos de aquisição","fields":[],"columns":["event_name","tenant","source","medium","campaign","value_amount","created_at"],"order":"-created_at","create":False,"edit":False},
    "meta-conversoes":{"model":"growth.MetaConversionLog","title":"Meta Conversions API","fields":[],"columns":["event_name","status","created_at"],"order":"-created_at","create":False,"edit":False},
    "usuarios":{"model":"accounts.User","title":"Usuários","fields":["tenant","email","role","is_active","is_staff"],"columns":["email","tenant","role","is_active","is_staff"],"order":"email"},
    "papeis-usuarios":{"model":"accounts.UserRole","title":"Papéis dos usuários","fields":["user","role"],"columns":["user","role"],"order":"user__email"},
}


def _guard(user):
    if not user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")


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
    cards=[{"slug":slug,"title":cfg["title"],"count":apps.get_model(cfg["model"]).objects.count()} for slug,cfg in MASTER_RESOURCES.items()]
    return render(request,"master/home.html",{"cards":cards})


@login_required
def resource_list(request,slug):
    _guard(request.user)
    config,model=_config(slug)
    qs=model.objects.all()
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
    headers=[str(_field(model,c).verbose_name).title() if _field(model,c) else c.replace("_"," ").title() for c in columns]
    rows=[{"obj":obj,"cells":[_value(obj,c) for c in columns]} for obj in qs[:300]]
    return render(request,"master/list.html",{"slug":slug,"resource":config,"headers":headers,"rows":rows,"q":q})


@login_required
def resource_form(request,slug,pk=None):
    _guard(request.user)
    config,model=_config(slug)
    if pk is None and not config.get("create",True): raise PermissionDenied
    if pk is not None and not config.get("edit",True): raise PermissionDenied
    obj=get_object_or_404(model,pk=pk) if pk else None
    Form=PlanMasterForm if config.get("special")=="plan" else modelform_factory(model,fields=config["fields"],widgets=_widgets(model,config["fields"]))
    form=Form(request.POST or None,instance=obj)
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
            form.add_error(None,exc)
    return render(request,"master/form.html",{"slug":slug,"resource":config,"form":form,"title":("Editar" if obj else "Novo")+" — "+config["title"]})


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
        if action in {"module-request-approve","module-request-reject"}:
            row=get_object_or_404(ModuleRequest,pk=pk)
            approved=action=="module-request-approve"
            review_module_request(
                module_request=row,user=request.user,approved=approved,
                note=request.POST.get("note",""),
            )
            if approved:
                activate_module_request(module_request=row,user=request.user)
                messages.success(request,"Módulo aprovado, ativado e incorporado à assinatura.")
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
