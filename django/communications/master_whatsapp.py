"""WhatsApp Web gateway and inbox restricted to platform superusers."""
import hmac
import json
import re

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tenants.models import Tenant
from .models import MasterWhatsAppConversation, MasterWhatsAppMessage


def _master(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")


def _gateway(method, path, payload=None):
    token=settings.MASTER_WHATSAPP_GATEWAY_TOKEN
    address=settings.MASTER_WHATSAPP_GATEWAY_URL
    if not token or not address:
        raise ValueError("Configure MASTER_WHATSAPP_GATEWAY_TOKEN para ativar o WhatsApp do Master.")
    try:
        response=requests.request(
            method,address.rstrip("/")+path,
            headers={"Authorization":"Bearer "+token},json=payload,timeout=12,
        )
        data=response.json()
    except (requests.RequestException,ValueError) as exc:
        raise ValueError("O serviço de WhatsApp do Master está indisponível.") from exc
    if not response.ok:
        raise ValueError(data.get("error") or "Não foi possível concluir a ação no WhatsApp.")
    return data


@login_required
def master_whatsapp_inbox(request):
    _master(request)
    if request.method=="POST":
        number=re.sub(r"\D","",request.POST.get("phone", ""))
        if not 10<=len(number)<=15:
            messages.error(request,"Informe um telefone com DDD e código do país, somente números.")
            return redirect("master-whatsapp")
        wa_id=number+"@s.whatsapp.net"
        row,_=MasterWhatsAppConversation.objects.get_or_create(
            wa_id=wa_id,defaults={"contact_name":(request.POST.get("name") or "")[:150],"last_message_at":timezone.now()},
        )
        return redirect("master-whatsapp-conversation",pk=row.pk)
    return render(request,"master/whatsapp_inbox.html",{
        "rows":MasterWhatsAppConversation.objects.select_related("tenant")[:200],
        "configured":bool(settings.MASTER_WHATSAPP_GATEWAY_TOKEN and settings.MASTER_WHATSAPP_GATEWAY_URL),
    })


@login_required
@require_GET
def master_whatsapp_status(request):
    _master(request)
    try:
        return JsonResponse(_gateway("GET","/status"))
    except ValueError as exc:
        return JsonResponse({"state":"unavailable","error":str(exc)},status=503)


@login_required
@require_POST
def master_whatsapp_connect(request):
    _master(request)
    try:
        _gateway("POST","/connect")
        messages.success(request,"Conexão iniciada. Aguarde o QR code nesta página.")
    except ValueError as exc:
        messages.error(request,str(exc))
    return redirect("master-whatsapp")


@login_required
@require_POST
def master_whatsapp_disconnect(request):
    _master(request)
    try:
        _gateway("POST","/disconnect")
        messages.success(request,"Dispositivo desvinculado do WhatsApp do Master.")
    except ValueError as exc:
        messages.error(request,str(exc))
    return redirect("master-whatsapp")


@login_required
def master_whatsapp_conversation(request,pk):
    _master(request)
    row=get_object_or_404(MasterWhatsAppConversation.objects.select_related("tenant"),pk=pk)
    if request.method=="POST":
        action=request.POST.get("action")
        if action=="assign":
            tenant_id=request.POST.get("tenant_id")
            tenant=Tenant.objects.filter(pk=tenant_id).first() if tenant_id else None
            if tenant_id and not tenant:
                messages.error(request,"Empresa não encontrada.")
            else:
                row.tenant=tenant
                row.save(update_fields=["tenant","updated_at"])
                messages.success(request,"Empresa associada à conversa.")
        elif action=="reply":
            body=(request.POST.get("body") or "").strip()
            if not body or len(body)>4096:
                messages.error(request,"Escreva uma mensagem de até 4096 caracteres.")
            else:
                try:
                    sent=_gateway("POST","/send",{"to":row.wa_id,"text":body})
                    MasterWhatsAppMessage.objects.create(
                        conversation=row,provider_message_id=sent["id"],direction="out",body=body,sent_by=request.user,
                    )
                    row.last_message_at=timezone.now()
                    row.save(update_fields=["last_message_at","updated_at"])
                    messages.success(request,"Mensagem enviada.")
                except (ValueError,KeyError) as exc:
                    messages.error(request,str(exc))
        return redirect("master-whatsapp-conversation",pk=row.pk)
    return render(request,"master/whatsapp_conversation.html",{
        "row":row,"thread":row.messages.select_related("sent_by")[:500],
        "tenants":Tenant.objects.filter(deleted_at__isnull=True).order_by("name")[:500],
    })


@csrf_exempt
@require_POST
def master_whatsapp_receive(request):
    """Only the internal gateway may write inbound platform messages."""
    expected=settings.MASTER_WHATSAPP_GATEWAY_TOKEN
    received=request.headers.get("Authorization","")
    if not expected or not hmac.compare_digest(received,"Bearer "+expected):
        return HttpResponse(status=403)
    try:
        data=json.loads(request.body)
        wa_id=str(data["from"])
        msg_id=str(data["id"])
        if not re.fullmatch(r"[0-9]{10,15}@s\.whatsapp\.net",wa_id) or not 1<=len(msg_id)<=190:
            raise ValueError
        body=str(data.get("text") or "")[:4096]
        name=str(data.get("name") or "")[:150]
    except (ValueError,TypeError,KeyError,json.JSONDecodeError):
        return JsonResponse({"error":"Mensagem inválida."},status=400)
    row,_=MasterWhatsAppConversation.objects.get_or_create(
        wa_id=wa_id,defaults={"contact_name":name,"last_message_at":timezone.now()},
    )
    _,created=MasterWhatsAppMessage.objects.get_or_create(
        provider_message_id=msg_id,defaults={"conversation":row,"direction":"in","body":body},
    )
    if created:
        row.contact_name=name or row.contact_name
        row.last_message_at=timezone.now()
        row.save(update_fields=["contact_name","last_message_at","updated_at"])
    return JsonResponse({"ok":True})
