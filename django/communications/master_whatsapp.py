"""WhatsApp Web gateway and inbox restricted to platform superusers."""
import base64
import hmac
from io import BytesIO
import json
import logging
import re
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from tenants.models import Tenant
from commercial.models import Lead, LeadHistory
from commercial.models import Proposal
from django.urls import reverse
from .models import (MasterWhatsAppConversation,MasterWhatsAppMessage,
    MasterWhatsAppDeliveryEvent,MasterWhatsAppFlow)

logger=logging.getLogger(__name__)


def _validated_attachment(uploaded):
    if not uploaded:
        return None
    if uploaded.size>5*1024*1024 or uploaded.size==0:
        raise ValueError("O anexo deve ter até 5 MB.")
    name=re.sub(r"[^A-Za-z0-9._-]","_",Path(uploaded.name).name)[:120] or "arquivo"
    suffix=Path(name).suffix.lower()
    data=uploaded.read()
    uploaded.seek(0)
    if suffix==".pdf" and data.startswith(b"%PDF-"):
        mime="application/pdf"
    elif suffix in {".png",".jpg",".jpeg",".webp"}:
        try:
            image=Image.open(BytesIO(data))
            if image.width*image.height>20_000_000:
                raise ValueError("A imagem tem resolução muito grande.")
            image.verify()
            mime={"PNG":"image/png","JPEG":"image/jpeg","WEBP":"image/webp"}.get(image.format)
        except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
            raise ValueError("Envie uma imagem PNG, JPG ou WebP válida.") from exc
        allowed_suffixes={"image/png":{".png"},"image/jpeg":{".jpg",".jpeg"},
                          "image/webp":{".webp"}}
        if suffix not in allowed_suffixes.get(mime,set()):
            raise ValueError("A extensão não corresponde à imagem enviada.")
    else:
        raise ValueError("Use imagem PNG/JPG/WebP ou documento PDF.")
    return {"base64":base64.b64encode(data).decode(),"mime":mime,"name":name}


def _apply_receipts(message):
    events=MasterWhatsAppDeliveryEvent.objects.filter(
        provider_message_id=message.provider_message_id,recipient_jid=message.recipient_jid,
    ).values_list("status","created_at")
    updates=[]
    for status,received in events:
        if status=="delivered" and not message.delivered_at:
            message.delivered_at=received
            updates.append("delivered_at")
        if status=="read" and not message.read_at:
            message.read_at=received
            message.delivered_at=message.delivered_at or received
            updates.extend(["read_at","delivered_at"])
    if message.read_at:
        message.delivery_status="read"
    elif message.delivered_at:
        message.delivery_status="delivered"
    if updates:
        message.save(update_fields=list(set(updates+["delivery_status"])))


def record_outbound_message(*,conversation,sent,body,sent_by,attachment=None,mime="",filename=""):
    recipient=sent.get("to") or conversation.wa_id
    if not re.fullmatch(r"[0-9]{10,20}@(s\.whatsapp\.net|lid)",recipient):
        raise ValueError("O WhatsApp não informou um destinatário válido.")
    with transaction.atomic():
        row=MasterWhatsAppMessage.objects.create(
            conversation=conversation,provider_message_id=sent["id"],direction="out",
            body=body,sent_by=sent_by,recipient_jid=recipient,
            attachment=attachment or "",attachment_mime=mime,attachment_name=filename,
        )
        _apply_receipts(row)
    return row


def _receipt_label(message,contact):
    if message.direction!="out":
        return ""
    if message.read_at:
        return f"{contact} leu às {timezone.localtime(message.read_at):%d/%m %H:%M}"
    if message.delivered_at:
        return f"{contact} recebeu às {timezone.localtime(message.delivered_at):%d/%m %H:%M}"
    return "Enviada · aguardando confirmação de entrega"


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
            headers={"Authorization":"Bearer "+token},json=payload,
            timeout=45 if payload and payload.get("file") else 12,
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
        lead_id=request.POST.get("lead_id","")
        tenant_id=request.POST.get("tenant_id","")
        lead=Lead.objects.filter(pk=lead_id,consent_granted=True,do_not_contact=False,
            anonymized_at__isnull=True).first() if lead_id.isdecimal() else None
        tenant=Tenant.objects.filter(pk=tenant_id,deleted_at__isnull=True).first() if tenant_id.isdecimal() else None
        if (lead_id and not lead) or (tenant_id and not tenant) or (lead_id and tenant_id):
            messages.error(request,"Contato indisponível para atendimento.")
            return redirect("master-whatsapp")
        number=re.sub(r"\D","",lead.phone if lead else tenant.phone if tenant else request.POST.get("phone", ""))
        if not 10<=len(number)<=15:
            messages.error(request,"Informe um telefone com DDD e código do país, somente números.")
            return redirect("master-whatsapp")
        wa_id=number+"@s.whatsapp.net"
        row,_=MasterWhatsAppConversation.objects.get_or_create(
            wa_id=wa_id,defaults={"contact_name":(lead.name if lead else tenant.name if tenant else request.POST.get("name") or "")[:150],
                "tenant":tenant,"last_message_at":timezone.now()},
        )
        return redirect("master-whatsapp-conversation",pk=row.pk)
    q=(request.GET.get("q") or "").strip()[:80]
    rows=MasterWhatsAppConversation.objects.select_related("tenant")
    if q:
        rows=rows.filter(Q(contact_name__icontains=q)|Q(wa_id__icontains=q)|Q(tenant__name__icontains=q))
    leads=Lead.objects.filter(consent_granted=True,do_not_contact=False,anonymized_at__isnull=True)
    companies=Tenant.objects.filter(deleted_at__isnull=True).exclude(phone="")
    if q:
        leads=leads.filter(Q(name__icontains=q)|Q(phone__icontains=q))
        companies=companies.filter(Q(name__icontains=q)|Q(phone__icontains=q))
    return render(request,"master/whatsapp_inbox.html",{
        "rows":rows[:200],"q":q,
        "leads":leads.order_by("-created_at")[:50],"companies":companies.order_by("name")[:50],
        "configured":bool(settings.MASTER_WHATSAPP_GATEWAY_TOKEN and settings.MASTER_WHATSAPP_GATEWAY_URL),
    })


@login_required
@require_GET
def master_whatsapp_status(request):
    _master(request)
    try:
        state=_gateway("GET","/status")
        latest=MasterWhatsAppConversation.objects.order_by("-last_message_at").values_list("pk","last_message_at").first()
        state["inbox_revision"]=f"{latest[0]}:{latest[1].isoformat()}" if latest else ""
        return JsonResponse(state)
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
        elif action=="create_lead":
            phone=row.wa_id.split("@")[0] if row.wa_id.endswith("@s.whatsapp.net") else ""
            if not phone:
                phone=re.sub(r"\D","",request.POST.get("phone", ""))
            if not 10<=len(phone)<=15:
                messages.error(request,"Informe o telefone com país e DDD para adicionar o contato ao Comercial.")
            else:
                with transaction.atomic():
                    lead=Lead.objects.select_for_update().filter(phone=phone,anonymized_at__isnull=True).first()
                    if not lead:
                        lead=Lead.objects.create(
                            name=row.contact_name or phone,phone=phone,email="",business_type="A identificar",
                            source="whatsapp_master",status=Lead.Status.IN_SERVICE,
                            assigned_to=request.user,assigned_at=timezone.now(),
                        )
                        LeadHistory.objects.create(lead=lead,action=LeadHistory.Action.CREATED,
                            to_user=request.user,actor_user=request.user,notes="Contato iniciado no WhatsApp do Master")
                messages.success(request,"Lead disponível no funil comercial.")
                return redirect("commercial-lead-detail",pk=lead.pk)
        elif action=="send_proposal":
            proposal_id=request.POST.get("proposal_id","")
            proposal=Proposal.objects.filter(pk=proposal_id).first() if proposal_id.isdecimal() else None
            if (not proposal or proposal.approval_status in {Proposal.Approval.PENDING,Proposal.Approval.REJECTED}
                or proposal.status in {Proposal.Status.CONVERTED,Proposal.Status.EXPIRED,Proposal.Status.CANCELLED}
                or proposal.expires_at and proposal.expires_at<=timezone.now()):
                messages.error(request,"Escolha uma proposta válida e aprovada para enviar.")
            else:
                link=request.build_absolute_uri(reverse("commercial-public-proposal",args=[proposal.public_token]))
                body=f"Sua proposta ApPlanner: {proposal.title}\n{link}"
                try:
                    sent=_gateway("POST","/send",{"to":row.wa_id,"text":body})
                    record_outbound_message(conversation=row,sent=sent,body=body,sent_by=request.user)
                except (ValueError,KeyError) as exc:
                    messages.error(request,str(exc))
                else:
                    if proposal.status==Proposal.Status.DRAFT:
                        proposal.status=Proposal.Status.SENT
                        proposal.save(update_fields=["status","updated_at"])
                    row.human_handoff=True
                    row.last_message_at=timezone.now()
                    row.save(update_fields=["human_handoff","last_message_at","updated_at"])
                    messages.success(request,"Link da proposta enviado por WhatsApp.")
        elif action=="handoff":
            row.human_handoff=request.POST.get("enabled")=="1"
            row.save(update_fields=["human_handoff","updated_at"])
            row.messages.filter(direction="in",flow_processed_at__isnull=True).update(flow_processed_at=timezone.now())
            messages.success(request,"Atendimento humano ativado." if row.human_handoff else "Fluxo automático retomado.")
        elif action=="reply":
            body=(request.POST.get("body") or "").strip()
            uploaded=request.FILES.get("attachment")
            if (not body and not uploaded) or len(body)>4096:
                messages.error(request,"Escreva uma mensagem ou selecione uma imagem/PDF de até 5 MB.")
            else:
                try:
                    attachment=_validated_attachment(uploaded)
                    payload={"to":row.wa_id,"text":body}
                    if attachment:
                        payload["file"]=attachment
                    sent=_gateway("POST","/send",payload)
                    record_outbound_message(conversation=row,sent=sent,body=body,sent_by=request.user,
                        attachment=uploaded,mime=attachment["mime"] if attachment else "",
                        filename=attachment["name"] if attachment else "")
                    row.human_handoff=True
                    row.messages.filter(direction="in",flow_processed_at__isnull=True).update(flow_processed_at=timezone.now())
                    row.last_message_at=timezone.now()
                    row.save(update_fields=["human_handoff","last_message_at","updated_at"])
                    messages.success(request,"Mensagem enviada. Acompanhe a entrega e leitura nesta conversa.")
                except (ValueError,KeyError) as exc:
                    messages.error(request,str(exc))
        return redirect("master-whatsapp-conversation",pk=row.pk)
    return render(request,"master/whatsapp_conversation.html",{
        "row":row,"thread":row.messages.select_related("sent_by")[:500],
        "conversations":MasterWhatsAppConversation.objects.select_related("tenant")[:100],
        "tenants":Tenant.objects.filter(deleted_at__isnull=True).order_by("name")[:500],
        "flow_enabled":MasterWhatsAppFlow.objects.filter(pk=1,enabled=True).exists(),
        "lead":Lead.objects.filter(phone=row.wa_id.split("@")[0],anonymized_at__isnull=True).first()
            if row.wa_id.endswith("@s.whatsapp.net") else None,
        "proposals":Proposal.objects.exclude(status__in=[Proposal.Status.CONVERTED,Proposal.Status.EXPIRED,
            Proposal.Status.CANCELLED]).exclude(approval_status__in=[Proposal.Approval.PENDING,
            Proposal.Approval.REJECTED]).order_by("-created_at")[:50],
    })


@login_required
@require_GET
def master_whatsapp_messages(request,pk):
    _master(request)
    row=get_object_or_404(MasterWhatsAppConversation,pk=pk)
    contact=row.contact_name or row.wa_id
    thread=list(row.messages.order_by("-id")[:200])
    from django.urls import reverse
    return JsonResponse({"messages":[{
        "id":item.pk,"body":item.body,"direction":item.direction,
        "time":timezone.localtime(item.created_at).strftime("%d/%m %H:%M"),
        "receipt":_receipt_label(item,contact),
        "attachment_url":reverse("master-whatsapp-attachment",args=[item.pk]) if item.attachment else "",
        "attachment_name":item.attachment_name,"attachment_mime":item.attachment_mime,
    } for item in reversed(thread)],"human_handoff":row.human_handoff})


@login_required
@require_GET
def master_whatsapp_attachment(request,pk):
    _master(request)
    item=get_object_or_404(MasterWhatsAppMessage,pk=pk)
    if not item.attachment:
        from django.http import Http404
        raise Http404
    try:
        response=FileResponse(item.attachment.open("rb"),content_type=item.attachment_mime or "application/octet-stream")
    except (FileNotFoundError,OSError):
        from django.http import Http404
        raise Http404 from None
    response["X-Content-Type-Options"]="nosniff"
    response["Cache-Control"]="private, no-store"
    response["Content-Disposition"]=f'attachment; filename="{item.attachment_name or "arquivo"}"'
    return response


@login_required
def master_whatsapp_flow(request):
    _master(request)
    from .master_whatsapp_flow import MasterFlowForm
    flow,_=MasterWhatsAppFlow.objects.get_or_create(pk=1)
    form=MasterFlowForm(request.POST or None,instance=flow)
    if request.method=="POST" and form.is_valid():
        if form.cleaned_data["enabled"] and not (
            settings.MASTER_WHATSAPP_GATEWAY_TOKEN and settings.MASTER_WHATSAPP_GATEWAY_URL
        ):
            form.add_error("enabled","Configure o WhatsApp do Master no Coolify antes de ativar o fluxo.")
        else:
            row=form.save(commit=False)
            row.steps=form.cleaned_data["steps_text"]
            row.save()
            messages.success(request,"Fluxo do Master salvo.")
            return redirect("master-whatsapp-flow")
    return render(request,"master/whatsapp_flow.html",{"form":form,"flow":flow})


@csrf_exempt
@require_POST
def master_whatsapp_receive(request):
    """Only the internal gateway may write inbound platform messages."""
    expected=settings.MASTER_WHATSAPP_GATEWAY_TOKEN
    received=request.headers.get("Authorization","")
    if not expected or not hmac.compare_digest(received,"Bearer "+expected):
        return HttpResponse(status=403)
    if len(request.body)>16384:
        return JsonResponse({"error":"Evento muito grande."},status=413)
    try:
        data=json.loads(request.body)
        if data.get("event")=="receipt":
            recipient=str(data["to"])
            msg_id=str(data["id"])
            status=str(data["status"])
            if (not re.fullmatch(r"[0-9]{10,20}@(s\.whatsapp\.net|lid)",recipient)
                or not 1<=len(msg_id)<=190 or status not in {"delivered","read"}):
                raise ValueError
            with transaction.atomic():
                MasterWhatsAppDeliveryEvent.objects.get_or_create(
                    provider_message_id=msg_id,recipient_jid=recipient,status=status,
                )
                message=MasterWhatsAppMessage.objects.select_for_update().filter(
                    provider_message_id=msg_id,recipient_jid=recipient,direction="out",
                ).first()
                if message:
                    _apply_receipts(message)
            return JsonResponse({"ok":True})
        wa_id=str(data["from"])
        msg_id=str(data["id"])
        if not re.fullmatch(r"[0-9]{10,20}@(s\.whatsapp\.net|lid)",wa_id) or not 1<=len(msg_id)<=190:
            raise ValueError
        body=str(data.get("text") or "")[:4096]
        name=str(data.get("name") or "")[:150]
    except (ValueError,TypeError,KeyError,json.JSONDecodeError):
        logger.warning("WhatsApp Master: evento recusado (formato inválido; valide JID, ID e status do recibo).")
        return JsonResponse({"error":"Evento inválido: confira o identificador do contato, o ID da mensagem e o tipo de recibo."},status=400)
    row,_=MasterWhatsAppConversation.objects.get_or_create(
        wa_id=wa_id,defaults={"contact_name":name,"last_message_at":timezone.now()},
    )
    incoming,created=MasterWhatsAppMessage.objects.get_or_create(
        provider_message_id=msg_id,defaults={"conversation":row,"direction":"in","body":body},
    )
    if created:
        row.contact_name=name or row.contact_name
        row.last_message_at=timezone.now()
        row.save(update_fields=["contact_name","last_message_at","updated_at"])
        if MasterWhatsAppFlow.objects.filter(pk=1,enabled=True).exists():
            from .tasks import process_master_chatbot
            try:
                process_master_chatbot.delay(incoming.pk)
            except Exception:
                # The inbound message stays stored and visible for manual response.
                logger.exception("Could not queue Master WhatsApp flow for message %s",incoming.pk)
    return JsonResponse({"ok":True})
