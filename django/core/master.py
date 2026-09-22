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
    "equipe-comercial":{"model":"commercial.CommercialProfile","title":"Equipe comercial","fields":["user","commission_percent","max_discount_percent","active"],"columns":["user","commission_percent","max_discount_percent","active"],"order":"user__email"},
    "comissoes-comerciais":{"model":"commercial.CommercialCommission","title":"Comissões comerciais","fields":["commercial_user","tenant","base_amount","commission_percent","commission_amount","status","hold_until"],"columns":["commercial_user","tenant","commission_amount","status","created_at"],"order":"-created_at"},
    "assinaturas":{"model":"billing.Subscription","title":"Assinaturas","fields":["tenant","plan","billing_cycle","contracted_price","status","started_at","trial_ends_at","next_billing_at","provider_customer_id","provider_subscription_id"],"columns":["tenant","plan","billing_cycle","status","next_billing_at"],"order":"-started_at"},
    "financeiro":{"model":"finance.PlatformFinancialTransaction","title":"Financeiro da plataforma","fields":["category","type","description","amount","status","due_at","paid_at","notes"],"columns":["type","description","amount","status","due_at"],"order":"-created_at","special":"platform_finance"},
    "suporte":{"model":"operations.SupportTicket","title":"Suporte","fields":["tenant","user","category","subject","description","priority","status","assigned_to"],"columns":["protocol","tenant","subject","priority","status","assigned_to"],"order":"-created_at","create":False},
    "incidentes":{"model":"operations.OperationalIncident","title":"Incidentes","fields":["category","severity","title","details","status"],"columns":["severity","title","status","occurrence_count","last_seen_at"],"order":"-last_seen_at","create":False},
    "backups":{"model":"operations.Backup","title":"Backups","fields":[],"columns":["type","scope","status","destination","size_bytes","completed_at"],"order":"-started_at","create":False,"edit":False},
    "homologacao":{"model":"operations.HomologationRun","title":"Homologações","fields":[],"columns":["status","score","executed_by","created_at"],"order":"-created_at","create":False,"edit":False},
    "legais":{"model":"legal.LegalDocument","title":"Documentos legais","fields":["type","version","title","content","status","published_at"],"columns":["type","version","title","status","published_at"],"order":"-published_at,-created_at"},
    "comerciais":{"model":"commercial.CommercialProfile","title":"Equipe comercial","fields":["user","commission_percent","max_discount_percent","active"],"columns":["user","commission_percent","max_discount_percent","active"],"order":"user__email"},
    "comissoes-comerciais":{"model":"commercial.CommercialCommission","title":"Comissões comerciais","fields":[],"columns":["commercial_user","tenant","base_amount","commission_amount","status","paid_at"],"order":"-created_at","create":False,"edit":False},
    "leads":{"model":"commercial.Lead","title":"Leads comerciais","fields":[],"columns":["name","business_type","status","assigned_to","next_contact_at","created_at"],"order":"-created_at","create":False,"edit":False},
    "propostas":{"model":"commercial.Proposal","title":"Propostas comerciais","fields":[],"columns":["title","customer_name","commercial_user","final_price","status","approval_status"],"order":"-created_at","create":False,"edit":False},
    "operacao":{"model":"operations.PlatformOperationSettings","title":"Configuração operacional","fields":["backup_retention_days","backup_include_uploads","backup_encrypt","backup_before_update","lead_retention_days","critical_alert_email","critical_alerts_enabled","cron_stale_minutes","disk_min_free_mb"],"columns":["backup_retention_days","backup_include_uploads","critical_alerts_enabled","cron_stale_minutes","disk_min_free_mb"],"order":"id","special":"operation_settings"},
    "crons":{"model":"operations.CronHeartbeat","title":"Saúde dos jobs","fields":[],"columns":["cron_key","status","started_at","finished_at","duration_ms","host_name"],"order":"-started_at","create":False,"edit":False},
    "imports":{"model":"operations.DataImportJob","title":"Implantações de bases","fields":[],"columns":["tenant","source","original_name","status","created_at","completed_at"],"order":"-created_at","create":False,"edit":False},
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
