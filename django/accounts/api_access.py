"""Personal, scoped, read-only integration API. Never serialize whole model instances."""
import hashlib
import secrets
from datetime import timedelta

from django import forms
from django.conf import settings
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from accounts.models import PersonalAPIToken,SecurityEvent
from accounts.permissions import has_capability
from billing.segment_access import segment_enabled
from core.portal import PORTAL_MODULES,_feature_allowed


# Explicit allowlist: no clinical records, credentials, messages, or payment secrets.
RESOURCES={
    "clientes":("agenda.read","scheduling.Customer",("id","name","phone","email","active")),
    "profissionais":("agenda.read","scheduling.Professional",("id","name","specialty","active")),
    "servicos":("agenda.read","scheduling.Service",("id","name","duration_minutes","price","active")),
    "agendamentos":("agenda.read","scheduling.Appointment",("id","customer_id","professional_id","service_id","starts_at","status")),
    "unidades":("agenda.read","tenants.Unit",("id","name","city","state","active")),
    "produtos":("finance.read","finance.Product",("id","name","sku","sale_price","stock","active")),
    "lancamentos":("finance.read","finance.FinancialTransaction",("id","type","description","amount","status","due_at")),
    "vendas":("finance.read","finance.Sale",("id","total","status","created_at")),
    "fila":("barber.read","barber.BarberQueueEntry",("id","customer_name","status","joined_at")),
    "reservas":("arena.read","arena.Reservation",("id","status","starts_at","ends_at")),
    "veiculos":("auto.read","auto.Vehicle",("id","plate","brand","model")),
    "chamados":("support.read","operations.SupportTicket",("id","protocol","subject","priority","status","created_at")),
    "leads":("commercial.read","commercial.Lead",("id","name","phone","email","business_type","status","source","notes","consent_granted","do_not_contact","next_contact_at","created_at","updated_at")),
    "propostas":("commercial.read","commercial.Proposal",("id","title","customer_name","final_price","status")),
}

FEATURE_RESOURCES={
    "produtos":("financeiro","produtos"),"lancamentos":("financeiro","lancamentos"),
    "vendas":("financeiro","pdv"),
}

GUIDES={
    "agenda":"Cadastre unidade, serviços e profissionais; ajuste expedientes, intervalos e folgas. Publique o link da empresa e confira os agendamentos confirmados. Registre atendimento, ausência ou cancelamento.",
    "financeiro":"Cadastre produtos e categorias; acompanhe lançamentos, vendas, caixa e comissões. Confira pagamento e conciliação antes de encerrar o caixa.",
    "barbearia":"Organize a fila, abra comandas, inclua serviços e produtos e encerre o atendimento. Consulte metas e remuneração.",
    "arena":"Cadastre quadras, horários e preços; administre reservas, jogos, mensalistas e torneios. Feche comandas e acompanhe ocupação.",
    "auto":"Cadastre veículos e boxes, abra ordens de serviço, faça inspeções com fotos e materiais, envie orçamento e registre a entrega.",
    "relacionamento":"Configure pacotes, mensalidades, fidelidade e indicações; acompanhe consumos, lista de espera e inteligência de retorno.",
    "saude":"Registre consentimento e acesse prontuários apenas conforme a permissão clínica. A leitura é auditada.",
    "comunicacao":"Gerencie notificações, campanhas e conversas. Para QR do WhatsApp, o módulo deve estar liberado e a sessão conectada.",
    "suporte":"Abra chamados, acompanhe o protocolo e registre a resolução. O acesso assistido exige consentimento explícito.",
}

SCOPES={
    "agenda.read":("Agenda, clientes, equipe e serviços","agenda.manage","agenda"),
    "finance.read":("Financeiro, produtos e vendas","finance.manage","financeiro"),
    "barber.read":("Fila da barbearia","barber.manage","barbearia"),
    "arena.read":("Reservas da arena","arena.manage","arena"),
    "auto.read":("Veículos da empresa","auto.manage","auto"),
    "professional.read":("Meus agendamentos","agenda.manage",None),
    "support.read":("Chamados da empresa","support.manage","suporte"),
    "commercial.read":("Meus leads e propostas","commercial.manage",None),
    "master.read":("Indicadores gerais da plataforma","*",None),
}


def allowed_scopes(user):
    if not user.is_active or user.must_change_password:
        return set()
    if user.blocks.filter(unblocked_at__isnull=True).filter(
        Q(expires_at__isnull=True)|Q(expires_at__gt=timezone.now())
    ).exists():
        return set()
    if user.is_superuser:
        return set(SCOPES)-{"professional.read"}
    if user.role=="commercial" and has_capability(user,"commercial.manage"):
        from commercial.models import CommercialProfile
        return {"commercial.read"} if CommercialProfile.objects.filter(user=user,active=True).exists() else set()
    if user.role=="support" and not user.tenant_id:
        return {"support.read"} if has_capability(user,"support.manage") else set()
    if not user.tenant_id or user.tenant.deleted_at or user.tenant.status not in ("active","trial"):
        return set()
    if user.role=="professional":
        return {"professional.read"} if apps.get_model("scheduling","Professional").objects.filter(
            user=user,tenant_id=user.tenant_id,active=True
        ).exists() else set()
    result=set()
    for slug,(_,capability,module_slug) in SCOPES.items():
        if slug in ("master.read","professional.read") or not has_capability(user,capability):
            continue
        if module_slug in ("barbearia","arena","auto") and not segment_enabled(user.tenant,module_slug):
            continue
        if slug=="finance.read" and not any(
            _feature_allowed(user,user.tenant,*feature) for feature in FEATURE_RESOURCES.values()
        ):
            continue
        result.add(slug)
    return result


class TokenForm(forms.Form):
    name=forms.CharField(label="Nome da integração",max_length=100)
    scopes=forms.MultipleChoiceField(label="Permitir consultas",widget=forms.CheckboxSelectMultiple)
    expires_in=forms.TypedChoiceField(label="Validade",coerce=int,choices=[(7,"7 dias"),(30,"30 dias"),(90,"90 dias")],initial=30)

    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["scopes"].choices=[(slug,SCOPES[slug][0]) for slug in sorted(allowed_scopes(user))]


@never_cache
@login_required
def documentation(request):
    user=request.user
    available=allowed_scopes(user)
    form=TokenForm(request.POST or None,user=user)
    issued=None
    if request.method=="POST" and not getattr(request,"support_actor",None) and form.is_valid():
        if user.api_tokens.filter(revoked_at__isnull=True,expires_at__gt=timezone.now()).count()>=20:
            form.add_error(None,"Revogue um token antes de criar outro. Limite de 20 tokens ativos.")
        else:
            raw="ap_"+secrets.token_urlsafe(48)
            token=PersonalAPIToken.objects.create(
                user=user,name=form.cleaned_data["name"],prefix=raw[:12],
                secret_hash=hashlib.sha256(raw.encode()).hexdigest(),
                scopes=form.cleaned_data["scopes"],tenant=None if user.is_superuser else user.tenant,
                session_version=user.session_version,
                expires_at=timezone.now()+timedelta(days=form.cleaned_data["expires_in"]),
            )
            SecurityEvent.objects.create(user=user,tenant=user.tenant,
                event_type="api_token_created",severity=SecurityEvent.Severity.MEDIUM,
                metadata={"token_id":token.pk,"scopes":token.scopes})
            issued=raw
            form=TokenForm(user=user)
    modules=[]
    if user.is_superuser:
        modules=[{"title":cfg["title"],"description":cfg["description"],"guide":GUIDES.get(slug,""),"resources":[{"title":r["title"],"url":f"/app/{slug}/{key}/"} for key,r in cfg["resources"].items()]} for slug,cfg in PORTAL_MODULES.items()]
    elif user.role=="professional":
        modules=[{"title":"Área profissional","description":"Agenda própria, conclusão e projeção de ganhos.","resources":[{"title":"Minha agenda e ganhos","url":"/app/profissional/"}]}]
    elif user.role=="commercial":
        modules=[{"title":"Comercial","description":"Captação, qualificação, propostas e comissões.","resources":[{"title":"Funil comercial","url":"/commercial/"}]}]
    elif user.role=="support" and not user.tenant_id:
        modules=[{"title":"Suporte da plataforma","description":"Chamados atribuídos e atendimento assistido.","resources":[{"title":"Chamados","url":"/master/suporte/"}]}]
    else:
        for slug,cfg in PORTAL_MODULES.items():
            if has_capability(user,cfg["capability"]) and (slug not in ("barbearia","arena","auto","saude") or segment_enabled(user.tenant,slug)):
                modules.append({"title":cfg["title"],"description":cfg["description"],"guide":GUIDES.get(slug,""),"resources":[{"title":r["title"],"url":f"/app/{slug}/{key}/"} for key,r in cfg["resources"].items() if _feature_allowed(user,user.tenant,slug,key)]})
    master=[]
    if user.is_superuser:
        from core.master import MASTER_RESOURCES
        master=[{"title":cfg["title"],"url":f"/master/{slug}/"} for slug,cfg in MASTER_RESOURCES.items()]
        master += [{"title":title,"url":url} for title,url in [
            ("WhatsApp Master","/master/whatsapp/"),("Fluxo comercial e chatbot","/master/whatsapp/fluxo/"),("Campanhas","/master/marketing/"),
            ("Chatbot","/master/chatbot/"),("Página inicial","/master/pagina-inicial/"),
            ("E-mail e SMTP","/master/email/smtp/"),("Modelos de e-mail","/master/email/modelos/"),
            ("Mercado Pago","/master/pagamentos/mercado-pago/")]]
    endpoint_rows=[{"key":key,"scope":scope,"fields":", ".join(fields)} for key,(scope,_,fields) in RESOURCES.items()
                   if scope in available and (user.is_superuser or key not in FEATURE_RESOURCES or
                       _feature_allowed(user,user.tenant,*FEATURE_RESOURCES[key]))]
    if "commercial.read" in available:
        endpoint_rows.append({"key":"planos-publicos","scope":"commercial.read","fields":"id, name, description, monthly_price, trial_days, trial_without_card, is_custom, modules"})
    if "master.read" in available:
        endpoint_rows.append({"key":"chatbot-master","scope":"master.read","fields":"enabled, updated_at, blocks, leads_linked, human_queue"})
    if "professional.read" in available:
        endpoint_rows.append({"key":"meus-agendamentos","scope":"professional.read","fields":"id, starts_at, status, service_id, customer_id"})
    return render(request,"accounts/documentation.html",{
        "form":form,"issued":issued,"tokens":user.api_tokens.all(),"modules":modules,
        "master":master,"endpoints":endpoint_rows,"available":available,"is_master":user.is_superuser,
    })


@login_required
def revoke_token(request,pk):
    if request.method!="POST":
        return JsonResponse({"erro":"Método não permitido."},status=405)
    if getattr(request,"support_actor",None):
        return JsonResponse({"erro":"Acesso assistido não pode gerenciar tokens."},status=403)
    token=get_object_or_404(PersonalAPIToken,user=request.user,pk=pk)
    if not token.revoked_at:
        token.revoked_at=timezone.now()
        token.save(update_fields=["revoked_at"])
        SecurityEvent.objects.create(user=request.user,tenant=request.user.tenant,
            event_type="api_token_revoked",severity=SecurityEvent.Severity.MEDIUM,
            metadata={"token_id":token.pk})
    return redirect("accounts:documentation")


def _authenticate(request):
    header=request.META.get("HTTP_AUTHORIZATION","")
    parts=header.split()
    if len(parts)!=2 or parts[0].lower()!="bearer" or not parts[1].startswith("ap_") or len(parts[1])>100:
        return None
    digest=hashlib.sha256(parts[1].encode()).hexdigest()
    token=PersonalAPIToken.objects.select_related("user","tenant","user__tenant").filter(
        secret_hash=digest,revoked_at__isnull=True,expires_at__gt=timezone.now(),user__is_active=True
    ).first()
    if not token or token.session_version!=token.user.session_version or token.user.must_change_password:
        return None
    if token.tenant_id!=token.user.tenant_id and not token.user.is_superuser:
        return None
    if not set(token.scopes).intersection(allowed_scopes(token.user)):
        return None
    return token


@never_cache
def api_resource(request,key,pk=None):
    if request.method!="GET":
        return JsonResponse({"erro":"Esta API aceita apenas GET."},status=405)
    token=_authenticate(request)
    if not token:
        response=JsonResponse({"erro":"Token inválido ou expirado."},status=401)
        response["WWW-Authenticate"]="Bearer"
        return response
    if getattr(settings,'SUBSCRIPTION_ACCESS_ENFORCED',True) and token.tenant_id and not token.user.is_superuser:
        from billing.access import current_subscription,subscription_allows_access
        if not subscription_allows_access(current_subscription(token.tenant)):
            return JsonResponse({'erro':'Acesso suspenso: regularize o pagamento da assinatura.','code':'subscription_payment_required'},status=402)
    # Read the minute once: add and incr must use the same key even at 00 seconds.
    limit_key=f"api:limit:{token.pk}:{timezone.now().strftime('%Y%m%d%H%M')}"
    if not cache.add(limit_key,1,timeout=75):
        count=cache.incr(limit_key)
        if count>60:
            return JsonResponse({"erro":"Limite de 60 requisições por minuto."},status=429)
    if key=="meus-agendamentos":
        scope="professional.read"
        model=apps.get_model("scheduling","Appointment")
        fields=("id","starts_at","status","service_id","customer_id")
    elif key in RESOURCES:
        scope,model_name,fields=RESOURCES[key]
        model=apps.get_model(model_name)
    elif key in {"visao-master","chatbot-master"}:
        scope="master.read"
    elif key=="planos-publicos":
        scope="commercial.read"
    else:
        return JsonResponse({"erro":"Recurso não encontrado."},status=404)
    if scope not in token.scopes or scope not in allowed_scopes(token.user):
        return JsonResponse({"erro":"Escopo não autorizado."},status=403)
    if key in FEATURE_RESOURCES and not token.user.is_superuser and not _feature_allowed(
        token.user,token.user.tenant,*FEATURE_RESOURCES[key]
    ):
        return JsonResponse({"erro":"Módulo não incluído no plano."},status=403)
    if key in {"chatbot-master","planos-publicos"}:
        if pk is not None:return JsonResponse({"erro":"Este recurso não possui detalhe por ID."},status=404)
        if key=="chatbot-master":
            if not token.user.is_superuser:return JsonResponse({"erro":"Acesso negado."},status=403)
            from communications.models import MasterWhatsAppFlow,MasterWhatsAppConversation
            flow=MasterWhatsAppFlow.objects.filter(pk=1).first()
            result={"enabled":bool(flow and flow.enabled),"updated_at":flow.updated_at if flow else None,
                    "blocks":len(flow.graph.get('nodes',[])) if flow else 0,
                    "leads_linked":MasterWhatsAppConversation.objects.filter(sales_lead__isnull=False).count(),
                    "human_queue":MasterWhatsAppConversation.objects.filter(human_handoff=True).count()}
        else:
            from communications.master_sales import plans_data
            result=plans_data()
        PersonalAPIToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return JsonResponse({"dados":result})
    if key=="visao-master":
        if not token.user.is_superuser:return JsonResponse({"erro":"Acesso negado."},status=403)
        from tenants.models import Tenant
        from billing.models import Plan,Subscription
        result={"empresas":Tenant.objects.count(),"planos":Plan.objects.count(),"assinaturas":Subscription.objects.count()}
        PersonalAPIToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return JsonResponse({"dados":result})
    tenant_id=token.tenant_id
    if token.user.is_superuser and key not in ("meus-agendamentos","leads","propostas"):
        from tenants.models import Tenant
        try:tenant_id=int(request.GET.get("empresa",""))
        except ValueError:return JsonResponse({"erro":"Informe empresa=<id> para consulta Master."},status=400)
        if not Tenant.objects.filter(pk=tenant_id,deleted_at__isnull=True).exists():
            return JsonResponse({"erro":"Empresa não encontrada."},status=404)
    qs=model.objects.all()
    if key=="meus-agendamentos":
        qs=qs.filter(tenant_id=token.tenant_id,professional__user_id=token.user_id)
    elif key=="leads":
        qs=qs if token.user.is_superuser else qs.filter(assigned_to=token.user)
    elif key=="propostas":
        qs=qs if token.user.is_superuser else qs.filter(commercial_user=token.user)
    elif key=="chamados" and token.user.role=="support" and not token.tenant_id:
        qs=qs.filter(assigned_to=token.user)
    else:
        qs=qs.filter(tenant_id=tenant_id)
    if pk is not None:
        row=qs.filter(pk=pk).values(*fields).first()
        if row is None:return JsonResponse({"erro":"Registro não encontrado."},status=404)
        data={"dados":row}
    else:
        try:page=int(request.GET.get("pagina","1"))
        except ValueError:page=0
        if page<1 or page>10000:return JsonResponse({"erro":"Página inválida."},status=400)
        data={"dados":list(qs.order_by("pk").values(*fields)[(page-1)*50:page*50]),"pagina":page,"limite":50}
    PersonalAPIToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return JsonResponse(data)
