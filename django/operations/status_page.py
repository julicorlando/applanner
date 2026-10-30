from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from billing.models import PaymentGateway
from communications.models import Notification,TenantWhatsAppConnection
from .models import OperationalIncident,PlatformOperationSettings,PlatformSMTPSettings


def _check_database():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()==(1,)
    except Exception:
        return False


def _check_cache():
    try:
        cache.set("status-page-check","ok",10)
        return cache.get("status-page-check")=="ok"
    except Exception:
        return False


def _service(key,label,state,detail):
    return {"key":key,"label":label,"state":state,"detail":detail}


def platform_status_snapshot():
    db_ok=_check_database()
    cache_ok=_check_cache()
    now=timezone.now()

    incidents=list(
        OperationalIncident.objects.filter(
            status__in=[OperationalIncident.Status.OPEN,OperationalIncident.Status.ACKNOWLEDGED]
        ).order_by("-severity","-last_seen_at")[:20]
    ) if db_ok else []

    critical_categories={
        str(row.category or "").lower()
        for row in incidents if row.severity==OperationalIncident.Severity.CRITICAL
    }
    warning_categories={
        str(row.category or "").lower()
        for row in incidents if row.severity==OperationalIncident.Severity.WARNING
    }

    app_state="operational" if db_ok and cache_ok else "outage"
    app_detail="Aplicação e serviços essenciais respondendo normalmente." if app_state=="operational" else "Há indisponibilidade em um serviço essencial."

    scheduling_bad=bool({"agenda","scheduling","database"} & critical_categories) or not db_ok
    scheduling_warn=bool({"agenda","scheduling"} & warning_categories)
    scheduling_state="outage" if scheduling_bad else "degraded" if scheduling_warn else "operational"

    payments_configured=False
    if db_ok:
        payments_configured=PaymentGateway.objects.filter(
            active=True,last_test_status=PaymentGateway.TestStatus.VALIDATED
        ).exists()
    payment_bad=bool({"billing","payment","payments"} & critical_categories)
    payment_warn=bool({"billing","payment","payments"} & warning_categories)
    payment_state=(
        "outage" if payment_bad
        else "degraded" if payment_warn
        else "operational" if payments_configured
        else "not_configured"
    )

    whatsapp_configured=bool(
        settings.MASTER_WHATSAPP_GATEWAY_URL
        or settings.WHATSAPP_GRAPH_BASE_URL
        or (db_ok and TenantWhatsAppConnection.objects.filter(enabled=True).exists())
    )
    wa_bad=bool({"whatsapp","communications"} & critical_categories)
    wa_warn=bool({"whatsapp","communications"} & warning_categories)
    wa_state=(
        "outage" if wa_bad
        else "degraded" if wa_warn
        else "operational" if whatsapp_configured
        else "not_configured"
    )

    smtp=None
    if db_ok:
        smtp=PlatformSMTPSettings.objects.filter(pk=1,enabled=True).first()
    email_configured=bool(smtp or settings.EMAIL_HOST)
    recent_email_failures=(
        Notification.objects.filter(
            channel=Notification.Channel.EMAIL,
            status=Notification.Status.FAILED,
            created_at__gte=now-timedelta(hours=1),
        ).count() if db_ok else 0
    )
    email_bad=bool({"email","smtp"} & critical_categories)
    email_warn=bool({"email","smtp"} & warning_categories) or recent_email_failures>=5
    email_state=(
        "outage" if email_bad
        else "degraded" if email_warn
        else "operational" if email_configured
        else "not_configured"
    )

    services=[
        _service("application","Aplicação",app_state,app_detail),
        _service(
            "scheduling","Agendamento",scheduling_state,
            "Agenda e disponibilidade operacionais." if scheduling_state=="operational"
            else "A agenda apresenta degradação ou indisponibilidade registrada.",
        ),
        _service(
            "payments","Pagamentos",payment_state,
            "Cobrança online operacional." if payment_state=="operational"
            else "Integração de cobrança sem configuração ativa." if payment_state=="not_configured"
            else "A cobrança online apresenta degradação ou indisponibilidade.",
        ),
        _service(
            "whatsapp","WhatsApp",wa_state,
            "Integração de mensagens operacional." if wa_state=="operational"
            else "WhatsApp não configurado para uso." if wa_state=="not_configured"
            else "A integração WhatsApp apresenta degradação ou indisponibilidade.",
        ),
        _service(
            "email","E-mail",email_state,
            "Envio transacional configurado." if email_state=="operational"
            else "E-mail transacional não configurado." if email_state=="not_configured"
            else "O envio de e-mails apresenta degradação ou indisponibilidade.",
        ),
    ]
    overall=(
        "outage" if any(item["state"]=="outage" for item in services)
        else "degraded" if any(item["state"]=="degraded" for item in services)
        else "operational"
    )
    return {"overall":overall,"services":services,"incidents":incidents,"checked_at":now}


def public_status(request):
    config=PlatformOperationSettings.objects.filter(pk=1).first()
    if config and not config.status_page_enabled and not request.user.is_superuser:
        raise Http404
    return render(request,"operations/status.html",platform_status_snapshot())
