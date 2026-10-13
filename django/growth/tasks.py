import hashlib
import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from .models import AcquisitionEvent,MetaConversionLog


def _sha(value):
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


@shared_task(bind=True,max_retries=4,autoretry_for=(Exception,),retry_backoff=True)
def send_meta_conversion(self,event_id,user_data=None):
    event=AcquisitionEvent.objects.get(event_id=event_id)
    log,_=MetaConversionLog.objects.get_or_create(
        event_id=event.event_id,defaults={"event_name":event.event_name}
    )
    if not event.marketing_consent or not settings.META_GRAPH_BASE_URL or not settings.META_CONVERSION_ACCESS_TOKEN or not settings.META_PIXEL_ID:
        log.status=MetaConversionLog.Status.SKIPPED
        log.save(update_fields=["status","updated_at"])
        return "skipped"
    data={}
    user_data=user_data or {}
    if user_data.get("email"):
        data["em"]=[_sha(user_data["email"])]
    if user_data.get("phone"):
        data["ph"]=[_sha(user_data["phone"])]
    payload={
        "data":[{
            "event_name":event.event_name,
            "event_time":int(event.created_at.timestamp()),
            "event_id":str(event.event_id),
            "action_source":"website",
            "event_source_url":event.event_url,
            "user_data":data,
            "custom_data":{
                "value":float(event.value_amount) if event.value_amount is not None else None,
                "currency":event.currency,
            },
        }],
        "access_token":settings.META_CONVERSION_ACCESS_TOKEN,
    }
    url=f"{settings.META_GRAPH_BASE_URL.rstrip('/')}/{settings.META_PIXEL_ID}/events"
    response=requests.post(url,json=payload,timeout=20)
    log.attempts+=1
    log.http_status=response.status_code
    log.response_excerpt=response.text[:500]
    log.status=MetaConversionLog.Status.SENT if response.ok else MetaConversionLog.Status.FAILED
    log.sent_at=timezone.now() if response.ok else None
    log.save()
    if not response.ok:
        raise RuntimeError(f"Meta CAPI HTTP {response.status_code}")
    return "sent"


@shared_task
def process_meta_conversion_queue(limit=100):
    ids=list(
        AcquisitionEvent.objects
        .filter(marketing_consent=True)
        .exclude(event_id__in=MetaConversionLog.objects.filter(
            status__in=[
                MetaConversionLog.Status.SENT,
                MetaConversionLog.Status.SKIPPED,
            ]
        ).values("event_id"))
        .order_by("created_at")
        .values_list("event_id",flat=True)[:limit]
    )
    for event_id in ids:
        send_meta_conversion.delay(str(event_id))
    return len(ids)
