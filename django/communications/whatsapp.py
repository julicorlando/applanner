import hashlib
import hmac
import requests

from django.conf import settings


class WhatsAppProviderError(RuntimeError):
    pass


def verify_webhook_signature(raw_body,signature):
    secret=settings.WHATSAPP_APP_SECRET
    if not secret or not signature.startswith("sha256="):
        return False
    expected=hmac.new(secret.encode(),raw_body,hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256="+expected,signature)


def send_text(to,text):
    if not settings.WHATSAPP_GRAPH_BASE_URL or not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        raise WhatsAppProviderError("WhatsApp Cloud API não configurada.")
    url=f"{settings.WHATSAPP_GRAPH_BASE_URL.rstrip('/')}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    response=requests.post(
        url,
        headers={"Authorization":f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}","Content-Type":"application/json"},
        json={"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text}},
        timeout=20,
    )
    try:
        payload=response.json()
    except ValueError:
        payload={}
    if not response.ok:
        raise WhatsAppProviderError(str(payload.get("error") or response.text)[:500])
    messages=payload.get("messages") or []
    return str(messages[0].get("id") or "") if messages else ""
