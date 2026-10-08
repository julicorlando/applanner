import json
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404,HttpResponse
from django.shortcuts import redirect,render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from .middleware import current_documents
from .models import DataSubjectRequest,LegalAcceptance


def _client_ip(request):
    forwarded=(request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


@login_required
def accept(request):
    docs=current_documents()
    accepted=set(LegalAcceptance.objects.filter(
        user=request.user,document_id__in=[d.pk for d in docs]
    ).values_list("document_id",flat=True))
    pending=[doc for doc in docs if doc.pk not in accepted]
    if not pending:
        return redirect("/")
    if request.method=="POST":
        if request.POST.get("accept")!="yes":
            return render(request,"legal/accept.html",{"documents":pending,"error":"É necessário aceitar os documentos para continuar."},status=400)
        for doc in pending:
            LegalAcceptance.objects.get_or_create(
                user=request.user,document=doc,
                defaults={
                    "tenant":getattr(request.user,"tenant",None),
                    "ip_address":_client_ip(request),
                    "user_agent":(request.META.get("HTTP_USER_AGENT") or "")[:500],
                },
            )
        destination=request.GET.get("next") or "/"
        if not url_has_allowed_host_and_scheme(
            destination,allowed_hosts={request.get_host()},require_https=request.is_secure(),
        ):
            destination="/"
        return redirect(destination)
    return render(request,"legal/accept.html",{"documents":pending})


PUBLIC_TYPES={
    "privacidade":"privacy",
    "termos-empresas":"terms_company",
    "termos-clientes":"terms_customer",
    "cancelamento-empresas":"cancellation_company",
    "cancelamento-clientes":"cancellation_customer",
}


def public_document(request,slug):
    doc_type=PUBLIC_TYPES.get(slug)
    if not doc_type:
        raise Http404
    from .models import LegalDocument
    document=(
        LegalDocument.objects.filter(type=doc_type,status=LegalDocument.Status.PUBLISHED)
        .order_by("-published_at","-created_at").first()
    )
    if not document:
        raise Http404
    return render(request,"legal/public_document.html",{"document":document,"slug":slug})



class DataSubjectRequestForm(forms.Form):
    request_type=forms.ChoiceField(
        choices=DataSubjectRequest.Type.choices,label="O que você deseja solicitar"
    )
    name=forms.CharField(max_length=160,label="Nome completo")
    email=forms.EmailField(label="E-mail para retorno")
    phone=forms.CharField(max_length=32,required=False,label="Telefone")
    details=forms.CharField(
        required=False,max_length=4000,label="Detalhes da solicitação",
        widget=forms.Textarea(attrs={"rows":5}),
    )


def _internal_deadline():
    return timezone.now()+timedelta(days=15)


def _create_dsr(*,request,request_type,name,email,phone="",details="",tenant=None,user=None,source):
    from core.audit import append_audit
    row=DataSubjectRequest.objects.create(
        tenant=tenant,user=user,request_type=request_type,
        requester_name=name.strip(),requester_email=email.strip().lower(),
        requester_phone=phone.strip(),details=details.strip(),
        deadline_at=_internal_deadline(),source=source,
        ip_address=_client_ip(request),
    )
    append_audit(
        tenant=tenant,user=user,request=request,
        action="DATA_SUBJECT_REQUEST_CREATED",
        entity_type="legal.DataSubjectRequest",entity_id=row.pk,
        after={"type":row.request_type,"deadline_at":row.deadline_at.isoformat()},
    )
    return row


@never_cache
@login_required
def privacy_center(request):
    if getattr(request,"support_actor",None):
        raise PermissionDenied("Preferências e solicitações de privacidade são pessoais e não podem ser alteradas pelo acesso assistido.")
    user=request.user
    if request.method=="POST":
        action=request.POST.get("action")
        if action in {"grant_marketing","withdraw_marketing"}:
            from core.audit import append_audit
            before={"marketing_consent":bool(user.marketing_consent)}
            enabled=action=="grant_marketing"
            user.marketing_consent=enabled
            user.marketing_consent_at=timezone.now() if enabled else None
            user.save(update_fields=["marketing_consent","marketing_consent_at"])
            append_audit(
                tenant=user.tenant,user=user,request=request,
                action="MARKETING_CONSENT_UPDATED",
                entity_type="accounts.User",entity_id=user.pk,
                before=before,after={"marketing_consent":enabled},
            )
            messages.success(
                request,
                "Consentimento de marketing atualizado. Mensagens transacionais da sua conta continuam funcionando."
            )
            return redirect("legal-privacy-center")

        if action in {"correction","deletion"}:
            details=(request.POST.get("details") or "").strip()
            if action=="correction" and not details:
                messages.error(request,"Descreva o dado que precisa ser corrigido.")
            else:
                row=_create_dsr(
                    request=request,
                    request_type=(
                        DataSubjectRequest.Type.CORRECTION
                        if action=="correction" else DataSubjectRequest.Type.DELETION
                    ),
                    name=(user.get_full_name() or user.first_name or user.email),
                    email=user.email,details=details,
                    tenant=user.tenant,user=user,source="privacy_center",
                )
                messages.success(
                    request,
                    f"Solicitação #{row.pk} registrada. Você pode acompanhar o status nesta página."
                )
            return redirect("legal-privacy-center")

    acceptances=LegalAcceptance.objects.filter(user=user).select_related("document").order_by("-accepted_at")
    requests=DataSubjectRequest.objects.filter(user=user).order_by("-created_at")
    return render(request,"legal/privacy_center.html",{
        "acceptances":acceptances,"requests":requests,
    })


@never_cache
@login_required
def privacy_export(request):
    if getattr(request,"support_actor",None):
        raise PermissionDenied("Dados pessoais da conta não podem ser exportados pelo acesso assistido.")
    user=request.user
    acceptances=LegalAcceptance.objects.filter(user=user).select_related("document").order_by("accepted_at")
    requests=DataSubjectRequest.objects.filter(user=user).order_by("created_at")
    login_history=user.login_history.order_by("created_at")[:500]
    tokens=user.api_tokens.order_by("created_at")[:200]
    payload={
        "generated_at":timezone.now().isoformat(),
        "account":{
            "id":user.pk,"email":user.email,"first_name":user.first_name,
            "last_name":user.last_name,"role":user.role,"locale":user.locale,
            "email_verified_at":user.email_verified_at.isoformat() if user.email_verified_at else None,
            "marketing_consent":user.marketing_consent,
            "marketing_consent_at":user.marketing_consent_at.isoformat() if user.marketing_consent_at else None,
            "date_joined":user.date_joined.isoformat() if user.date_joined else None,
        },
        "company":{
            "id":user.tenant_id,
            "name":user.tenant.name if user.tenant_id else None,
        },
        "legal_acceptances":[
            {
                "document":row.document.title,"type":row.document.type,
                "version":row.document.version,"accepted_at":row.accepted_at.isoformat(),
            }
            for row in acceptances
        ],
        "privacy_requests":[
            {
                "id":row.pk,"type":row.request_type,"status":row.status,
                "created_at":row.created_at.isoformat(),
                "deadline_at":row.deadline_at.isoformat() if row.deadline_at else None,
                "completed_at":row.completed_at.isoformat() if row.completed_at else None,
            }
            for row in requests
        ],
        "login_history":[
            {
                "successful":row.successful,"ip_address":str(row.ip_address or ""),
                "user_agent":row.user_agent,"created_at":row.created_at.isoformat(),
            }
            for row in login_history
        ],
        "api_tokens":[
            {
                "name":row.name,"prefix":row.prefix,
                "created_at":row.created_at.isoformat(),
                "expires_at":row.expires_at.isoformat(),
                "revoked_at":row.revoked_at.isoformat() if row.revoked_at else None,
            }
            for row in tokens
        ],
    }
    from core.audit import append_audit
    append_audit(
        tenant=user.tenant,user=user,request=request,
        action="PERSONAL_DATA_EXPORTED",
        entity_type="accounts.User",entity_id=user.pk,
        after={"sections":list(payload.keys())},
    )
    response=HttpResponse(
        json.dumps(payload,ensure_ascii=False,indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"]=f'attachment; filename="applanner-meus-dados-{user.pk}.json"'
    return response


def public_privacy_request(request):
    from tenants.models import Tenant
    tenant=None
    tenant_slug=(request.GET.get("tenant") or request.POST.get("tenant_slug") or "").strip()
    if tenant_slug:
        tenant=Tenant.objects.filter(
            public_slug=tenant_slug,deleted_at__isnull=True
        ).first()
    form=DataSubjectRequestForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        data=form.cleaned_data
        row=_create_dsr(
            request=request,request_type=data["request_type"],
            name=data["name"],email=data["email"],phone=data["phone"],
            details=data["details"],tenant=tenant,user=None,source="public_request",
        )
        messages.success(
            request,
            f"Solicitação #{row.pk} registrada. A equipe poderá pedir validação de identidade antes de fornecer ou excluir dados."
        )
        return redirect("legal-public-privacy-request")
    return render(request,"legal/privacy_request.html",{
        "form":form,"tenant":tenant,"tenant_slug":tenant_slug,
    })
