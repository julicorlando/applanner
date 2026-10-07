import json
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from tenants.models import Tenant
from .models import ChatbotFlow, MarketingDelivery, MarketingLead, WhatsAppConversation, WhatsAppMessage
from .chatbot import next_reply
from .tasks import send_chatbot_reply
from .whatsapp import verify_webhook_signature


@csrf_exempt
@transaction.atomic
def whatsapp_webhook(request):
    if request.method=="GET":
        if (
            settings.WHATSAPP_VERIFY_TOKEN
            and request.GET.get("hub.mode")=="subscribe"
            and request.GET.get("hub.verify_token")==settings.WHATSAPP_VERIFY_TOKEN
        ):
            return HttpResponse(request.GET.get("hub.challenge",""))
        return HttpResponse(status=403)
    if request.method!="POST":
        return HttpResponse(status=405)
    if not verify_webhook_signature(request.body,request.headers.get("X-Hub-Signature-256","")):
        return HttpResponse(status=401)
    try:
        payload=json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError):
        return HttpResponse(status=400)

    for entry in payload.get("entry",[]):
        for change in entry.get("changes",[]):
            value=change.get("value") or {}
            metadata=value.get("metadata") or {}
            phone_number_id=str(metadata.get("phone_number_id") or "")
            tenant=Tenant.objects.filter(metadata__whatsapp_phone_number_id=phone_number_id).first()
            if not tenant:
                continue
            flow=ChatbotFlow.objects.filter(tenant=tenant,enabled=True).first()
            contacts={str(c.get("wa_id")):(c.get("profile") or {}).get("name","") for c in value.get("contacts",[])}
            for message in value.get("messages",[]):
                wa_id=str(message.get("from") or "")
                if not wa_id or not message.get("id"):
                    continue
                conversation,first_message=WhatsAppConversation.objects.get_or_create(
                    tenant=tenant,wa_id=wa_id,
                    defaults={
                        "contact_name":contacts.get(wa_id,""),
                        "last_message_at":timezone.now(),
                    },
                )
                body=((message.get("text") or {}).get("body") or "")
                incoming,created=WhatsAppMessage.objects.get_or_create(
                    provider_message_id=str(message.get("id") or ""),
                    defaults={
                        "conversation":conversation,"tenant":tenant,
                        "direction":WhatsAppMessage.Direction.IN,
                        "sender_type":WhatsAppMessage.SenderType.CUSTOMER,
                        "message_type":str(message.get("type") or "text"),
                        "body":body,"status":WhatsAppMessage.Status.RECEIVED,"chatbot_transport":"cloud",
                    },
                )
                if not created:
                    continue
                from .tenant_whatsapp import mark_inbound_appointment
                if mark_inbound_appointment(conversation,body):
                    continue
                conversation.context={**conversation.context,"_chatbot_transport":"cloud"}
                conversation.save(update_fields=['context','updated_at'])
                if flow and flow.graph and message.get('type')=='text' and phone_number_id==settings.WHATSAPP_PHONE_NUMBER_ID:
                    from .tenant_graph_services import enqueue
                    transaction.on_commit(lambda pk=incoming.pk:enqueue(pk))
                    continue
                incoming.flow_processed_at=timezone.now()
                incoming.save(update_fields=["flow_processed_at"])
                reply=None
                if flow and message.get("type")=="text" and phone_number_id==settings.WHATSAPP_PHONE_NUMBER_ID:
                    reply,conversation.status=next_reply(flow,conversation,body,first_message=first_message)
                elif any(term in body.lower() for term in ("atendente","humano","falar com alguém")):
                    conversation.status=WhatsAppConversation.Status.WAITING_HUMAN
                conversation.last_message_at=timezone.now()
                conversation.save(update_fields=["status","last_message_at","updated_at"])
                if reply:
                    send_chatbot_reply.delay(conversation.pk,reply)
    return JsonResponse({"ok":True})


def marketing_open(request,token):
    delivery=MarketingDelivery.objects.filter(tracking_token=token).first()
    if delivery and not delivery.opened_at:
        delivery.opened_at=timezone.now()
        delivery.save(update_fields=["opened_at","updated_at"])
    pixel=bytes.fromhex("47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b")
    return HttpResponse(pixel,content_type="image/gif")


def marketing_unsubscribe(request,token):
    from django.shortcuts import render
    lead=MarketingLead.objects.filter(unsubscribe_token=token).first()
    if not lead:
        return HttpResponse(status=404)
    if request.method=="POST" and lead.status!=MarketingLead.Status.UNSUBSCRIBED:
        lead.status=MarketingLead.Status.UNSUBSCRIBED
        lead.unsubscribed_at=timezone.now()
        lead.save(update_fields=["status","unsubscribed_at","updated_at"])
    return render(request,"communications/unsubscribe.html",{"unsubscribed":lead.status==MarketingLead.Status.UNSUBSCRIBED})


def marketing_click(request,token):
    from django.shortcuts import redirect
    delivery=MarketingDelivery.objects.select_related("campaign").filter(tracking_token=token).first()
    if not delivery or not delivery.campaign.card_link_url:
        return HttpResponse(status=404)
    if not delivery.clicked_at:
        delivery.clicked_at=timezone.now()
        delivery.save(update_fields=["clicked_at","updated_at"])
    return redirect(delivery.campaign.card_link_url)
