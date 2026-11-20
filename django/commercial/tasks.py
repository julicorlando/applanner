from celery import shared_task
from django.utils import timezone

from .models import Lead
from .services import anonymize_lead


@shared_task
def enforce_lead_retention(limit=200):
    rows=Lead.objects.filter(
        anonymized_at__isnull=True,
        retention_until__isnull=False,
        retention_until__lte=timezone.now(),
    ).order_by("retention_until")[:limit]
    count=0
    for lead in rows:
        anonymize_lead(lead=lead)
        count+=1
    return count
