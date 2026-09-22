from datetime import timedelta
import secrets

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied, ValidationError
from django.db.models import Q
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.permissions import has_capability,require_any_capability
from arena.services import ArenaReservationService
from healthcare.services import create_record, read_record


PORTAL_MODULES = {
    "agenda": {
        "capability":"agenda.manage",
        "title": "Agenda",
        "description": "Clientes, equipe, serviços e agendamentos.",
        "resources": {
            "agendamentos": {
                "model": "scheduling.Appointment",
                "title": "Agendamentos",
                "fields": ["customer","professional","service","starts_at","status","source","notes"],
                "columns": ["starts_at","customer","service","professional","status"],
                "order": "-starts_at",
                "special": "appointment",
            },
            "clientes": {
                "model": "scheduling.Customer",
                "title": "Clientes",
                "fields": ["name","phone","email","birth_date","consent_marketing","active"],
                "columns": ["name","phone","email","active"],
                "order": "name",
            },
            "profissionais": {
                "model": "scheduling.Professional",
                "title": "Profissionais",
                "fields": ["unit","name","public_slug","email","phone","specialty","commission_percent","active"],
                "columns": ["name","specialty","phone","active"],
                "order": "name",
            },
            "servicos": {
                "model": "scheduling.Service",
                "title": "Serviços",
                "fields": ["name","description","duration_minutes","price","active"],
                "columns": ["name","duration_minutes","price","active"],
                "order": "name",
            },
        },
    },
    "financeiro": {
        "capability":"finance.manage",
        "title": "Financeiro & Estoque",
        "description": "Receitas, despesas, produtos e estoque.",
        "resources": {
            "lancamentos": {
                "model": "finance.FinancialTransaction",
                "title": "Lançamentos",
                "fields": ["category","type","description","amount","payment_method","competence_at","status","due_at"],
                "columns": ["type","description","amount","status","due_at"],
                "order": "-created_at",
                "special": "financial_transaction",
            },
            "produtos": {
                "model": "finance.Product",
                "title": "Produtos",
                "fields": ["unit","name","sku","code","category","description","cost_price","sale_price","stock","minimum_stock","unit_label","commission_type","commission_value","active"],
                "columns": ["name","sku","sale_price","stock","minimum_stock","active"],
                "order": "name",
            },
            "pdv": {
                "model": "finance.Sale",
                "title": "PDV / Vendas",
                "fields": [],
                "columns": ["id","customer","total","payment_method","status","created_at"],
                "order": "-created_at",
                "create": False,
                "edit": False,
                "custom_list": "finance_pos",
            },
            "caixa": {
                "model": "finance.CashSession",
                "title": "Caixa",
                "fields": [],
                "columns": ["unit","opening_amount","status","opened_at","closed_at"],
                "order": "-opened_at",
                "create": False,
                "edit": False,
                "custom_list": "finance_cash",
            },
            "comissoes": {
                "model": "finance.ProfessionalCommission",
                "title": "Comissões",
                "fields": [],
                "columns": ["professional","gross_amount","commission_amount","status","created_at"],
                "order": "-created_at",
                "create": False,
                "edit": False,
                "custom_list": "finance_commissions",
            },
        },
    },
    "barbearia": {
        "capability":"barber.manage",
        "title": "Barbearia & Salão",
        "description": "Fila e comandas do atendimento.",
        "resources": {
            "fila": {
                "model": "barber.BarberQueueEntry",
                "title": "Fila de atendimento",
                "fields": ["customer","customer_name","customer_phone","service","preferred_professional","assigned_professional","status","priority","notes"],
                "columns": ["customer_name","service","preferred_professional","assigned_professional","status","joined_at"],
                "order": "-priority,joined_at",
                "special": "barber_queue",
            },
            "comandas": {
                "model": "barber.BarberCommand",
                "title": "Comandas",
                "fields": [],
                "columns": ["customer","professional","status","total_amount","opened_at"],
                "order": "-opened_at",
                "custom_create": "barber_command",
                "edit": False,
                "detail": "barber_command",
            },
            "metas": {
                "model": "barber.ProfessionalGoal",
                "title": "Metas profissionais",
                "fields": ["professional","year","month","revenue_target","services_target","products_target","ticket_target"],
                "columns": ["professional","year","month","revenue_target","services_target","ticket_target"],
                "order": "-year,-month",
            },
            "remuneracao": {
                "model": "barber.ProfessionalCompensationModel",
                "title": "Remuneração",
                "fields": ["professional","model","monthly_rent","daily_rent","rent_due_day","service_commission_percent","notes"],
                "columns": ["professional","model","monthly_rent","daily_rent","service_commission_percent"],
                "order": "professional__name",
            },
        },
    },
    "arena": {
        "capability":"arena.manage",
        "title": "Arena & Quadras",
        "description": "Quadras, reservas, mensalistas, turmas e torneios.",
        "resources": {
            "quadras": {
                "model": "arena.Court",
                "title": "Quadras",
                "fields": ["unit","name","slug","description","surface","indoor","lighting","capacity","minimum_minutes","maximum_minutes","interval_minutes","active","sort_order"],
                "columns": ["name","surface","minimum_minutes","maximum_minutes","active"],
                "order": "sort_order,name",
            },
            "reservas": {
                "model": "arena.Reservation",
                "title": "Reservas",
                "fields": [],
                "columns": ["starts_at","court","customer_name","duration_minutes","total_amount","status","payment_status"],
                "order": "-starts_at",
                "custom_create": "arena_reservation",
                "edit": False,
            },
            "mensalistas": {
                "model": "arena.Membership",
                "title": "Mensalistas",
                "fields": ["customer","court","modality","name","frequency","weekday","day_of_month","start_time","duration_minutes","monthly_amount","start_date","end_date","next_generation_date","generate_days_ahead","status","notes"],
                "columns": ["name","customer","court","frequency","monthly_amount","status"],
                "order": "name",
                "special": "arena_membership",
            },
            "turmas": {
                "model": "arena.SportsClass",
                "title": "Turmas / Escolinha",
                "fields": ["court","modality","teacher_name","name","level","weekday","start_time","duration_minutes","capacity","monthly_amount","status"],
                "columns": ["name","teacher_name","court","weekday","start_time","status"],
                "order": "name",
            },
            "jogos": {
                "model": "arena.Game",
                "title": "Jogos / Rachas",
                "fields": [],
                "columns": ["name","court","starts_at","max_players","status"],
                "order": "-starts_at",
                "create": False,
                "edit": False,
                "custom_list": "arena_games",
            },
            "alunos": {
                "model": "arena.ClassStudent",
                "title": "Alunos de turmas",
                "fields": ["sports_class","customer","responsible_name","responsible_phone","monthly_amount_override","billing_day","status","joined_at"],
                "columns": ["customer","sports_class","status","joined_at"],
                "order": "-joined_at",
            },
            "reposicoes": {
                "model": "arena.ClassMakeup",
                "title": "Reposições",
                "fields": ["student","original_class","original_date","replacement_class","replacement_date","status","notes"],
                "columns": ["student","original_class","original_date","replacement_class","replacement_date","status"],
                "order": "-original_date",
            },
            "torneios": {
                "model": "arena.Tournament",
                "title": "Torneios",
                "fields": ["modality","name","category","format","registration_amount","starts_on","ends_on","status"],
                "columns": ["name","category","format","starts_on","status"],
                "order": "-starts_on",
                "detail": "arena_tournament",
            },
            "comandas": {
                "model": "arena.ArenaCommand",
                "title": "Comandas Arena",
                "fields": [],
                "columns": ["public_id","customer","status","total","payment_status","opened_at"],
                "order": "-opened_at",
                "create": False,
                "edit": False,
                "custom_list": "arena_commands",
            },
        },
    },
    "auto": {
        "capability":"auto.manage",
        "title": "Automotivo",
        "description": "Veículos, boxes e ordens de serviço.",
        "resources": {
            "veiculos": {
                "model": "auto.Vehicle",
                "title": "Veículos",
                "fields": ["customer","plate","brand","model","year","color","notes","active"],
                "columns": ["plate","brand","model","customer","active"],
                "order": "plate",
            },
            "boxes": {
                "model": "auto.ServiceBay",
                "title": "Boxes / Vagas",
                "fields": ["name","bay_type","capacity","buffer_minutes","notes","active","sort_order"],
                "columns": ["name","bay_type","capacity","active"],
                "order": "sort_order,name",
            },
            "ordens": {
                "model": "auto.Job",
                "title": "Ordens de serviço",
                "fields": ["appointment","vehicle","bay","assigned_professional","status","odometer_in","fuel_level","keys_received","expected_ready_at","internal_notes","public_notes"],
                "columns": ["appointment","vehicle","bay","assigned_professional","status","expected_ready_at"],
                "order": "-created_at",
                "detail": "auto_job",
            },
            "orcamentos": {
                "model": "auto.Estimate",
                "title": "Orçamentos",
                "fields": [],
                "columns": ["job","status","total_amount","expires_at","created_at"],
                "order": "-created_at",
                "create": False,
                "edit": False,
            },
            "pacotes-veiculos": {
                "model": "auto.VehiclePackageLink",
                "title": "Pacotes vinculados a veículos",
                "fields": ["customer_package","vehicle"],
                "columns": ["customer_package","vehicle","created_at"],
                "order": "-created_at",
            },
            "mensalidades-veiculos": {
                "model": "auto.MembershipVehicleLink",
                "title": "Mensalidades vinculadas a veículos",
                "fields": ["membership","vehicle"],
                "columns": ["membership","vehicle","created_at"],
                "order": "-created_at",
            },
        },
    },
    "relacionamento": {
        "capability":"engagement.manage",
        "title": "Relacionamento",
        "description": "Pacotes, recorrência, fidelidade e lista de espera.",
        "resources": {
            "pacotes": {
                "model": "engagement.ServicePackage",
                "title": "Pacotes de serviços",
                "fields": ["name","description","price","validity_days","active","recurring"],
                "columns": ["name","price","validity_days","recurring","active"],
                "order": "name",
            },
            "pacotes-clientes": {
                "model": "engagement.CustomerPackage",
                "title": "Pacotes dos clientes",
                "fields": ["customer","package","expires_at","status","purchase_amount","external_reference"],
                "columns": ["customer","package","status","purchase_amount","expires_at"],
                "order": "-purchased_at",
                "special": "customer_package",
                "custom_list": "engagement_packages",
            },
            "recorrencias": {
                "model": "engagement.CustomerMembership",
                "title": "Recorrências",
                "fields": ["customer","package","cycle","recurring_amount","status","started_at","next_due_at","provider_subscription_id"],
                "columns": ["customer","package","cycle","recurring_amount","next_due_at","status"],
                "order": "next_due_at",
            },
            "fidelidade": {
                "model": "engagement.LoyaltyAccount",
                "title": "Fidelidade",
                "fields": [],
                "columns": ["customer","points","updated_at"],
                "order": "-points",
                "create": False,
                "edit": False,
                "custom_list": "engagement_loyalty",
            },
            "dominios": {
                "model": "engagement.TenantDomain",
                "title": "Domínios personalizados",
                "fields": [],
                "columns": ["domain","status","verified_at"],
                "order": "-created_at",
                "create": False,
                "edit": False,
                "custom_list": "engagement_domains",
            },
            "espera": {
                "model": "engagement.WaitlistEntry",
                "title": "Lista de espera",
                "fields": ["customer","service","professional","preferred_date","period","status","notes"],
                "columns": ["customer","service","professional","preferred_date","period","status"],
                "order": "preferred_date,created_at",
                "custom_list": "engagement_waitlist",
            },
        },
    },
    "saude": {
        "capability":"healthcare.manage",
        "title": "Saúde",
        "description": "Prontuário clínico criptografado.",
        "resources": {
            "prontuarios": {
                "model": "healthcare.MedicalRecordEntry",
                "title": "Prontuários",
                "fields": [],
                "columns": ["created_at","customer","professional","record_type","title"],
                "order": "-created_at",
                "custom_create": "medical_record",
                "edit": False,
                "detail": "medical_record",
            },
        },
    },
    "suporte": {
        "capability":"support.manage",
        "title": "Suporte",
        "description": "Chamados e acompanhamento.",
        "resources": {
            "chamados": {
                "model": "operations.SupportTicket",
                "title": "Chamados",
                "fields": ["category","subject","description","priority","status"],
                "columns": ["protocol","subject","category","priority","status","created_at"],
                "order": "-created_at",
                "special": "support_ticket",
                "detail": "support_ticket",
            },
        },
    },
}


def _field(model, name):
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _tenant(request):
    if not request.user.is_authenticated:
        return None
    if request.user.tenant_id:
        return request.user.tenant
    if request.user.is_superuser:
        tenant_id=request.session.get("portal_tenant_id")
        if tenant_id:
            Tenant=apps.get_model("tenants","Tenant")
            return Tenant.objects.filter(pk=tenant_id).first()
    return None


def _require_tenant(request):
    tenant=_tenant(request)
    if tenant:
        return tenant
    if request.user.is_superuser:
        return None
    raise PermissionDenied("Seu usuário não está vinculado a uma empresa.")


def _require_module_access(user,module):
    capability=module.get("capability")
    if capability:
        require_any_capability(user,capability)


def _resource(module_slug, resource_slug):
    module=PORTAL_MODULES.get(module_slug)
    if not module:
        raise Http404
    resource=module["resources"].get(resource_slug)
    if not resource:
        raise Http404
    model=apps.get_model(resource["model"])
    return module,resource,model


def _tenant_queryset(model, tenant):
    qs=model.objects.all()
    if _field(model,"tenant"):
        qs=qs.filter(tenant=tenant)
    return qs


def _apply_order(qs, order):
    if not order:
        return qs
    fields=[part.strip() for part in order.split(",") if part.strip()]
    return qs.order_by(*fields)


def _scope_form(form, tenant):
    for form_field in form.fields.values():
        qs=getattr(form_field,"queryset",None)
        if qs is None:
            continue
        related=qs.model
        if _field(related,"tenant"):
            form_field.queryset=qs.filter(tenant=tenant)
        elif related._meta.label_lower=="tenants.unit":
            form_field.queryset=qs.filter(tenant=tenant)
    return form


def _widgets_for(model, fields):
    widgets={}
    for name in fields:
        field=_field(model,name)
        if not field:
            continue
        internal=field.get_internal_type()
        if internal=="DateTimeField":
            widgets[name]=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M")
        elif internal=="DateField":
            widgets[name]=forms.DateInput(attrs={"type":"date"})
        elif internal=="TimeField":
            widgets[name]=forms.TimeInput(attrs={"type":"time"})
        elif internal=="TextField":
            widgets[name]=forms.Textarea(attrs={"rows":4})
    return widgets


def _model_form(model, resource, *args, tenant=None, **kwargs):
    Form=modelform_factory(model,fields=resource["fields"],widgets=_widgets_for(model,resource["fields"]))
    form=Form(*args,**kwargs)
    for name,field in form.fields.items():
        model_field=_field(model,name)
        if model_field and model_field.get_internal_type()=="DateTimeField":
            field.input_formats=["%Y-%m-%dT%H:%M","%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M"]
    return _scope_form(form,tenant)


class ArenaReservationForm(forms.Form):
    court=forms.ModelChoiceField(queryset=apps.get_model("arena","Court").objects.none(),label="Quadra")
    modality=forms.ModelChoiceField(queryset=apps.get_model("arena","Modality").objects.none(),required=False,label="Modalidade")
    customer=forms.ModelChoiceField(queryset=apps.get_model("scheduling","Customer").objects.none(),required=False,label="Cliente cadastrado")
    customer_name=forms.CharField(max_length=160,label="Nome do cliente")
    customer_phone=forms.CharField(max_length=30,label="Telefone")
    customer_email=forms.EmailField(required=False,label="E-mail")
    starts_at=forms.DateTimeField(label="Início",widget=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M"),input_formats=["%Y-%m-%dT%H:%M"])
    duration_minutes=forms.IntegerField(min_value=15,initial=60,label="Duração (minutos)")
    payment_method=forms.CharField(max_length=20,initial="onsite",label="Forma de pagamento")
    notes=forms.CharField(required=False,widget=forms.Textarea(attrs={"rows":3}),label="Observações")

    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["court"].queryset=apps.get_model("arena","Court").objects.filter(tenant=tenant,active=True)
        self.fields["modality"].queryset=apps.get_model("arena","Modality").objects.filter(tenant=tenant,active=True)
        self.fields["customer"].queryset=apps.get_model("scheduling","Customer").objects.filter(tenant=tenant,active=True)


class MedicalRecordForm(forms.Form):
    customer=forms.ModelChoiceField(queryset=apps.get_model("scheduling","Customer").objects.none(),label="Paciente")
    professional=forms.ModelChoiceField(queryset=apps.get_model("scheduling","Professional").objects.none(),label="Profissional")
    appointment=forms.ModelChoiceField(queryset=apps.get_model("scheduling","Appointment").objects.none(),required=False,label="Agendamento")
    record_type=forms.ChoiceField(choices=apps.get_model("healthcare","MedicalRecordEntry").Type.choices,label="Tipo")
    title=forms.CharField(max_length=190,label="Título")
    content=forms.CharField(widget=forms.Textarea(attrs={"rows":10}),label="Conteúdo clínico")

    def __init__(self,*args,tenant=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["customer"].queryset=apps.get_model("scheduling","Customer").objects.filter(tenant=tenant,active=True)
        self.fields["professional"].queryset=apps.get_model("scheduling","Professional").objects.filter(tenant=tenant,active=True)
        self.fields["appointment"].queryset=apps.get_model("scheduling","Appointment").objects.filter(tenant=tenant).order_by("-starts_at")[:500]


def _save_special(obj, *, resource, request, tenant, is_new):
    special=resource.get("special")
    if _field(obj.__class__,"tenant"):
        obj.tenant=tenant

    if special=="appointment":
        if obj.service_id and obj.starts_at:
            obj.ends_at=obj.starts_at+timedelta(minutes=obj.service.duration_minutes)
            obj.service_price_snapshot=obj.service.price
        if is_new:
            obj.created_by=request.user
    elif special=="financial_transaction":
        if obj.status==obj.Status.PAID and not obj.paid_at:
            obj.paid_at=timezone.now()
    elif special=="barber_queue":
        if is_new:
            obj.joined_at=timezone.now()
        if obj.customer_id:
            obj.customer_name=obj.customer_name or obj.customer.name
            obj.customer_phone=obj.customer_phone or obj.customer.phone
    elif special=="customer_package":
        if is_new:
            obj.purchased_at=timezone.now()
    elif special=="arena_membership":
        if is_new:
            obj.created_by=request.user
    elif special=="support_ticket":
        if is_new:
            obj.user=request.user
            obj.protocol=f"SUP-{tenant.pk}-{timezone.now():%Y%m%d%H%M}-{secrets.token_hex(2).upper()}"
    return obj


def _value(obj, name):
    getter=getattr(obj,f"get_{name}_display",None)
    if getter:
        try:
            return getter()
        except Exception:
            pass
    value=getattr(obj,name,None)
    if value is None or value=="":
        return "—"
    if isinstance(value,bool):
        return "Sim" if value else "Não"
    if hasattr(value,"strftime"):
        try:
            local=timezone.localtime(value) if timezone.is_aware(value) else value
            return local.strftime("%d/%m/%Y %H:%M")
        except Exception:
            try:
                return value.strftime("%d/%m/%Y")
            except Exception:
                return str(value)
    return str(value)


def _headers(model, columns):
    result=[]
    for name in columns:
        field=_field(model,name)
        result.append(str(field.verbose_name).title() if field else name.replace("_"," ").title())
    return result


@login_required
def home(request):
    if request.user.is_superuser and request.GET.get("trocar")=="1":
        request.session.pop("portal_tenant_id",None)
    tenant=_require_tenant(request)
    if tenant is None:
        Tenant=apps.get_model("tenants","Tenant")
        return render(request,"portal/select_tenant.html",{"tenants":Tenant.objects.order_by("name")})

    modules=[]
    for slug,module in PORTAL_MODULES.items():
        capability=module.get("capability")
        if capability and not has_capability(request.user,capability):
            continue
        resources=[]
        for resource_slug,resource in module["resources"].items():
            resources.append({"slug":resource_slug,"title":resource["title"]})
        modules.append({"slug":slug,"title":module["title"],"description":module["description"],"resources":resources})
    return render(request,"portal/home.html",{"tenant":tenant,"modules":modules})


@login_required
def select_tenant(request, tenant_id):
    if not request.user.is_superuser:
        raise PermissionDenied
    Tenant=apps.get_model("tenants","Tenant")
    tenant=get_object_or_404(Tenant,pk=tenant_id)
    request.session["portal_tenant_id"]=tenant.pk
    messages.success(request,f"Empresa de homologação: {tenant.name}.")
    return redirect("portal-home")


@login_required
def resource_list(request,module_slug,resource_slug):
    module_for_access=PORTAL_MODULES.get(module_slug)
    if not module_for_access: raise Http404
    _require_module_access(request.user,module_for_access)
    module,resource,model=_resource(module_slug,resource_slug)
    if resource.get("custom_list")=="arena_games":
        return redirect("arena-games")
    if resource.get("custom_list")=="arena_commands":
        return redirect("arena-commands")
    if resource.get("custom_list")=="finance_pos":
        return redirect("finance-pos")
    if resource.get("custom_list")=="finance_cash":
        return redirect("finance-cash")
    if resource.get("custom_list")=="finance_commissions":
        return redirect("finance-commissions")
    if resource.get("custom_list")=="engagement_packages":
        return redirect("engagement-packages")
    if resource.get("custom_list")=="engagement_loyalty":
        return redirect("engagement-loyalty")
    if resource.get("custom_list")=="engagement_waitlist":
        return redirect("engagement-waitlist")
    if resource.get("custom_list")=="engagement_domains":
        return redirect("engagement-domains")
    tenant=_require_tenant(request)
    if tenant is None:
        return redirect("portal-home")
    qs=_tenant_queryset(model,tenant)
    q=(request.GET.get("q") or "").strip()
    if q:
        lookup=Q()
        for field in model._meta.fields:
            if field.get_internal_type() in {"CharField","TextField","EmailField","SlugField"}:
                lookup |= Q(**{f"{field.name}__icontains":q})
        if lookup:
            qs=qs.filter(lookup)
    qs=_apply_order(qs,resource.get("order"))[:300]
    columns=resource["columns"]
    rows=[{"obj":obj,"cells":[_value(obj,c) for c in columns]} for obj in qs]
    return render(request,"portal/list.html",{
        "tenant":tenant,"module_slug":module_slug,"module":module,
        "resource_slug":resource_slug,"resource":resource,
        "headers":_headers(model,columns),"rows":rows,"q":q,
        "can_create":resource.get("create",True) or bool(resource.get("custom_create")),
        "can_edit":resource.get("edit",True),
    })


@login_required
def resource_create(request,module_slug,resource_slug):
    module_for_access=PORTAL_MODULES.get(module_slug)
    if not module_for_access: raise Http404
    _require_module_access(request.user,module_for_access)
    tenant=_require_tenant(request)
    if tenant is None:
        return redirect("portal-home")
    module,resource,model=_resource(module_slug,resource_slug)
    custom=resource.get("custom_create")

    if custom=="barber_command":
        return redirect("barber-command-create")
    if custom=="arena_reservation":
        form=ArenaReservationForm(request.POST or None,tenant=tenant)
        if request.method=="POST" and form.is_valid():
            data=form.cleaned_data
            start=data["starts_at"]
            end=start+timedelta(minutes=data["duration_minutes"])
            try:
                reservation,_token=ArenaReservationService().create_reservation(
                    tenant=tenant,court=data["court"],start=start,end=end,
                    customer_name=data["customer_name"],customer_phone=data["customer_phone"],
                    customer_email=data["customer_email"],customer=data["customer"],
                    modality=data["modality"],payment_method=data["payment_method"],
                    source=model.Source.INTERNAL,created_by=request.user,notes=data["notes"],
                    accept_terms=False,public_rules=False,
                )
                messages.success(request,f"Reserva {reservation.public_id} criada.")
                return redirect("portal-resource-list",module_slug=module_slug,resource_slug=resource_slug)
            except ValidationError as exc:
                form.add_error(None,exc)
    elif custom=="medical_record":
        form=MedicalRecordForm(request.POST or None,tenant=tenant)
        if request.method=="POST" and form.is_valid():
            data=form.cleaned_data
            try:
                create_record(
                    tenant=tenant,customer=data["customer"],professional=data["professional"],
                    appointment=data["appointment"],record_type=data["record_type"],
                    title=data["title"],content=data["content"],user=request.user,
                    ip=request.META.get("REMOTE_ADDR",""),
                )
                messages.success(request,"Prontuário criado e criptografado.")
                return redirect("portal-resource-list",module_slug=module_slug,resource_slug=resource_slug)
            except (ValidationError,PermissionDenied) as exc:
                form.add_error(None,exc)
    else:
        if not resource.get("create",True):
            raise PermissionDenied
        form=_model_form(model,resource,request.POST or None,tenant=tenant)
        if request.method=="POST" and form.is_valid():
            obj=form.save(commit=False)
            obj=_save_special(obj,resource=resource,request=request,tenant=tenant,is_new=True)
            try:
                obj.full_clean()
                obj.save()
                form.save_m2m()
                messages.success(request,f"{resource['title']}: cadastro criado.")
                return redirect("portal-resource-list",module_slug=module_slug,resource_slug=resource_slug)
            except ValidationError as exc:
                form.add_error(None,exc)

    return render(request,"portal/form.html",{
        "tenant":tenant,"module_slug":module_slug,"module":module,
        "resource_slug":resource_slug,"resource":resource,"form":form,
        "title":f"Novo — {resource['title']}",
    })


@login_required
def resource_edit(request,module_slug,resource_slug,pk):
    module_for_access=PORTAL_MODULES.get(module_slug)
    if not module_for_access: raise Http404
    _require_module_access(request.user,module_for_access)
    tenant=_require_tenant(request)
    if tenant is None:
        return redirect("portal-home")
    module,resource,model=_resource(module_slug,resource_slug)
    if not resource.get("edit",True):
        raise PermissionDenied
    obj=get_object_or_404(_tenant_queryset(model,tenant),pk=pk)
    form=_model_form(model,resource,request.POST or None,instance=obj,tenant=tenant)
    if request.method=="POST" and form.is_valid():
        obj=form.save(commit=False)
        obj=_save_special(obj,resource=resource,request=request,tenant=tenant,is_new=False)
        try:
            obj.full_clean()
            obj.save()
            form.save_m2m()
            messages.success(request,"Alterações salvas.")
            return redirect("portal-resource-list",module_slug=module_slug,resource_slug=resource_slug)
        except ValidationError as exc:
            form.add_error(None,exc)
    return render(request,"portal/form.html",{
        "tenant":tenant,"module_slug":module_slug,"module":module,
        "resource_slug":resource_slug,"resource":resource,"form":form,
        "title":f"Editar — {resource['title']}",
    })


@login_required
def resource_detail(request,module_slug,resource_slug,pk):
    module_for_access=PORTAL_MODULES.get(module_slug)
    if not module_for_access: raise Http404
    _require_module_access(request.user,module_for_access)
    tenant=_require_tenant(request)
    if tenant is None:
        return redirect("portal-home")
    module,resource,model=_resource(module_slug,resource_slug)
    obj=get_object_or_404(_tenant_queryset(model,tenant),pk=pk)
    if resource.get("detail")=="barber_command":
        return redirect("barber-command-detail",pk=obj.pk)
    if resource.get("detail")=="auto_job":
        return redirect("auto-job-detail",pk=obj.pk)
    if resource.get("detail")=="arena_tournament":
        return redirect("arena-tournament-detail",pk=obj.pk)
    if resource.get("detail")=="arena_class":
        return redirect("arena-class-detail",pk=obj.pk)
    if resource.get("detail")=="medical_record":
        content=read_record(entry=obj,user=request.user,ip=request.META.get("REMOTE_ADDR",""))
        return render(request,"portal/medical_record.html",{
            "tenant":tenant,"module_slug":module_slug,"module":module,
            "resource_slug":resource_slug,"resource":resource,"entry":obj,"content":content,
        })
    raise Http404
