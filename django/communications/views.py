import json
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from tenants.models import Tenant
from .models import MarketingDelivery, WhatsAppConversation, WhatsAppMessage
from .whatsapp import verify_webhook_signature


@csrf_exempt
def whatsapp_webhook(request):
    if request.method=="GET":
        if (
            request.GET.get("hub.mode")=="subscribe"
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
            contacts={str(c.get("wa_id")):(c.get("profile") or {}).get("name","") for c in value.get("contacts",[])}
            for message in value.get("messages",[]):
                wa_id=str(message.get("from") or "")
                if not wa_id:
                    continue
                conversation,_=WhatsAppConversation.objects.get_or_create(
                    tenant=tenant,wa_id=wa_id,
                    defaults={
                        "contact_name":contacts.get(wa_id,""),
                        "last_message_at":timezone.now(),
                    },
                )
                body=((message.get("text") or {}).get("body") or "")
                WhatsAppMessage.objects.get_or_create(
                    provider_message_id=str(message.get("id") or ""),
                    defaults={
                        "conversation":conversation,"tenant":tenant,
                        "direction":WhatsAppMessage.Direction.IN,
                        "sender_type":WhatsAppMessage.SenderType.CUSTOMER,
                        "message_type":str(message.get("type") or "text"),
                        "body":body,"status":WhatsAppMessage.Status.RECEIVED,
                    },
                )
                if any(term in body.lower() for term in ("atendente","humano","falar com alguém")):
                    conversation.status=WhatsAppConversation.Status.WAITING_HUMAN
                conversation.last_message_at=timezone.now()
                conversation.save(update_fields=["status","last_message_at","updated_at"])
    return JsonResponse({"ok":True})


def marketing_open(request,token):
    delivery=MarketingDelivery.objects.filter(tracking_token=token).first()
    if delivery and not delivery.opened_at:
        delivery.opened_at=timezone.now()
        delivery.save(update_fields=["opened_at","updated_at"])
    pixel=bytes.fromhex("47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b")
    return HttpResponse(pixel,content_type="image/gif")


def marketing_click(request,token):
    from django.shortcuts import redirect
    delivery=MarketingDelivery.objects.select_related("campaign").filter(tracking_token=token).first()
    if not delivery or not delivery.campaign.card_link_url:
        return HttpResponse(status=404)
    if not delivery.clicked_at:
        delivery.clicked_at=timezone.now()
        delivery.save(update_fields=["clicked_at","updated_at"])
    return redirect(delivery.campaign.card_link_url)
