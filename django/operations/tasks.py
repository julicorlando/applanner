import socket
import time

from celery import shared_task
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from .models import CronHeartbeat,OperationalIncident
from .services import record_incident


@shared_task
def platform_health_check():
    start=time.monotonic()
    heartbeat=CronHeartbeat.objects.create(
        cron_key="platform_health",
        started_at=timezone.now(),
        status="running",
        host_name=socket.gethostname(),
    )
    errors=[]
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        errors.append("database:"+str(exc)[:180])
        record_incident(
            category="database",
            severity=OperationalIncident.Severity.CRITICAL,
            title="Falha no health check do PostgreSQL",
            details=str(exc)[:1000],
        )
    try:
        cache.set("health_probe","ok",20)
        if cache.get("health_probe")!="ok":
            raise RuntimeError("Redis probe mismatch")
    except Exception as exc:
        errors.append("cache:"+str(exc)[:180])
        record_incident(
            category="application",
            severity=OperationalIncident.Severity.CRITICAL,
            title="Falha no health check do Redis",
            details=str(exc)[:1000],
        )
    heartbeat.finished_at=timezone.now()
    heartbeat.duration_ms=int((time.monotonic()-start)*1000)
    heartbeat.status="failed" if errors else "ok"
    heartbeat.details="; ".join(errors)[:500]
    heartbeat.save(update_fields=["finished_at","duration_ms","status","details"])
    return heartbeat.status
