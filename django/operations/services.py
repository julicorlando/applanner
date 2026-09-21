import hashlib
import shutil
from decimal import Decimal

from django.core.cache import cache
from django.db import connection,transaction
from django.utils import timezone

from .models import HomologationRun,OperationalIncident,PlatformOperationSettings


@transaction.atomic
def record_incident(*,category,severity,title,details=""):
    fingerprint=hashlib.sha256(f"{category}|{title}".encode()).hexdigest()
    now=timezone.now()
    incident=OperationalIncident.objects.select_for_update().filter(fingerprint=fingerprint).first()
    if incident:
        incident.occurrence_count+=1
        incident.last_seen_at=now
        incident.severity=severity
        incident.details=details
        if incident.status==OperationalIncident.Status.RESOLVED:
            incident.status=OperationalIncident.Status.OPEN
            incident.resolved_at=None
            incident.resolved_by=None
        incident.save()
        return incident
    return OperationalIncident.objects.create(
        fingerprint=fingerprint,
        category=category,
        severity=severity,
        title=title,
        details=details,
        status=OperationalIncident.Status.OPEN,
        first_seen_at=now,
        last_seen_at=now,
    )


def run_homologation(*,user):
    checks={}
    score=Decimal("100.00")
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"]=cursor.fetchone()[0]==1
    except Exception as exc:
        checks["database"]=False
        checks["database_error"]=str(exc)[:200]
        score-=Decimal("35")
    try:
        cache.set("homologation_probe","ok",30)
        checks["cache"]=cache.get("homologation_probe")=="ok"
    except Exception as exc:
        checks["cache"]=False
        checks["cache_error"]=str(exc)[:200]
        score-=Decimal("15")

    settings_obj,_=PlatformOperationSettings.objects.get_or_create(pk=1)
    free_mb=shutil.disk_usage("/").free//(1024*1024)
    checks["disk_free_mb"]=free_mb
    if free_mb<settings_obj.disk_min_free_mb:
        checks["disk"]=False
        score-=Decimal("20")
    else:
        checks["disk"]=True

    critical=OperationalIncident.objects.filter(
        status__in=[OperationalIncident.Status.OPEN,OperationalIncident.Status.ACKNOWLEDGED],
        severity=OperationalIncident.Severity.CRITICAL,
    ).count()
    checks["critical_incidents"]=critical
    if critical:
        score-=min(Decimal("30"),Decimal(critical*5))

    score=max(Decimal("0"),score)
    status=(
        HomologationRun.Status.PASSED if score>=Decimal("90")
        else HomologationRun.Status.WARNING if score>=Decimal("70")
        else HomologationRun.Status.BLOCKED
    )
    return HomologationRun.objects.create(
        status=status,score=score,results=checks,executed_by=user
    )
