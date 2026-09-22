from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Q
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone


MASTER_RESOURCES={
    "empresas":{"model":"tenants.Tenant","title":"Empresas","fields":["name","slug","public_slug","category","email","phone","status","public_enabled","public_booking_enabled","locale","timezone"],"columns":["name","slug","category","status","created_at"],"order":"-created_at"},
    "planos":{"model":"billing.Plan","title":"Planos","fields":["name","slug","description","monthly_price","quarterly_price","semiannual_price","annual_price","trial_days","trial_without_card","active","featured","sort_order"],"columns":["name","monthly_price","trial_days","active","featured"],"order":"sort_order,name"},
    "assinaturas":{"model":"billing.Subscription","title":"Assinaturas","fields":["tenant","plan","billing_cycle","contracted_price","status","started_at","trial_ends_at","next_billing_at","provider_customer_id","provider_subscription_id"],"columns":["tenant","plan","billing_cycle","status","next_billing_at"],"order":"-started_at"},
    "financeiro":{"model":"finance.PlatformFinancialTransaction","title":"Financeiro da plataforma","fields":["category","type","description","amount","status","due_at","paid_at","notes"],"columns":["type","description","amount","status","due_at"],"order":"-created_at","special":"platform_finance"},
    "suporte":{"model":"operations.SupportTicket","title":"Suporte","fields":["tenant","user","category","subject","description","priority","status","assigned_to"],"columns":["protocol","tenant","subject","priority","status","assigned_to"],"order":"-created_at","create":False},
    "incidentes":{"model":"operations.OperationalIncident","title":"Incidentes","fields":["category","severity","title","details","status"],"columns":["severity","title","status","occurrence_count","last_seen_at"],"order":"-last_seen_at","create":False},
    "backups":{"model":"operations.Backup","title":"Backups","fields":[],"columns":["type","scope","status","destination","size_bytes","completed_at"],"order":"-started_at","create":False,"edit":False},
    "homologacao":{"model":"operations.HomologationRun","title":"Homologações","fields":[],"columns":["status","score","executed_by","created_at"],"order":"-created_at","create":False,"edit":False},
    "legais":{"model":"legal.LegalDocument","title":"Documentos legais","fields":["type","version","title","content","status","published_at"],"columns":["type","version","title","status","published_at"],"order":"-published_at,-created_at"},
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
    Form=modelform_factory(model,fields=config["fields"],widgets=_widgets(model,config["fields"]))
    form=Form(request.POST or None,instance=obj)
    for name,field in form.fields.items():
        mf=_field(model,name)
        if mf and mf.get_internal_type()=="DateTimeField":
            field.input_formats=["%Y-%m-%dT%H:%M","%Y-%m-%d %H:%M:%S"]
    if request.method=="POST" and form.is_valid():
        row=form.save(commit=False)
        if config.get("special")=="platform_finance" and not row.created_by_id:
            row.created_by=request.user
        try:
            row.full_clean()
            row.save()
            form.save_m2m()
            messages.success(request,"Registro salvo.")
            return redirect("master-resource-list",slug=slug)
        except ValidationError as exc:
            form.add_error(None,exc)
    return render(request,"master/form.html",{"slug":slug,"resource":config,"form":form,"title":("Editar" if obj else "Novo")+" — "+config["title"]})
