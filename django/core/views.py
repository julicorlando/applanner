from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone


def healthz(request):
    checks={"database":False,"cache":False}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"]=cursor.fetchone()==(1,)
    except Exception:
        checks["database"]=False

    try:
        cache.set("healthz","ok",10)
        checks["cache"]=cache.get("healthz")=="ok"
    except Exception:
        checks["cache"]=False

    healthy=all(checks.values())
    return JsonResponse(
        {"status":"ok" if healthy else "degraded","checks":checks},
        status=200 if healthy else 503,
    )


def _tenant_dashboard(request):
    from billing.entitlements import active_subscription
    from billing.models import TenantModule
    from finance.models import FinancialTransaction
    from scheduling.models import Appointment,Customer,Professional

    tenant=request.user.tenant
    now=timezone.localtime()
    start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    end=start+timedelta(days=1)
    month_start=start.replace(day=1)

    today_qs=Appointment.objects.filter(
        tenant=tenant,starts_at__gte=start,starts_at__lt=end
    )
    revenue=FinancialTransaction.objects.filter(
        tenant=tenant,
        type=FinancialTransaction.Type.INCOME,
        status=FinancialTransaction.Status.PAID,
        paid_at__gte=month_start,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    modules=list(
        TenantModule.objects.filter(
            tenant=tenant,enabled=True,module__active=True
        ).select_related("module").order_by("module__sort_order","module__name")
    )
    subscription=active_subscription(tenant)
    if subscription:
        plan_modules=list(
            subscription.plan.module_links.filter(
                enabled=True,module__active=True
            ).select_related("module")
        )
        known={row.module_id for row in modules}
        modules.extend(row for row in plan_modules if row.module_id not in known)

    return render(request,"dashboard.html",{
        "tenant":tenant,
        "today_total":today_qs.count(),
        "today_pending":today_qs.filter(status__in=[
            Appointment.Status.PENDING,Appointment.Status.CONFIRMED
        ]).count(),
        "customers":Customer.objects.filter(tenant=tenant,active=True).count(),
        "professionals":Professional.objects.filter(tenant=tenant,active=True).count(),
        "revenue":revenue,
        "next_appointments":today_qs.select_related(
            "customer","service","professional"
        ).order_by("starts_at")[:8],
        "modules":modules,
        "subscription":subscription,
    })


def _platform_dashboard(request):
    from billing.models import Subscription
    from commercial.models import Lead
    from operations.models import OperationalIncident
    from tenants.models import Tenant

    return render(request,"platform_dashboard.html",{
        "tenants_total":Tenant.objects.count(),
        "tenants_active":Tenant.objects.filter(status=Tenant.Status.ACTIVE).count(),
        "subscriptions_active":Subscription.objects.filter(status=Subscription.Status.ACTIVE).count(),
        "open_leads":Lead.objects.filter(status__in=[
            Lead.Status.NEW,Lead.Status.IN_SERVICE,Lead.Status.CONTACTED,Lead.Status.QUALIFIED
        ]).count(),
        "critical_incidents":OperationalIncident.objects.filter(
            status__in=[OperationalIncident.Status.OPEN,OperationalIncident.Status.ACKNOWLEDGED],
            severity=OperationalIncident.Severity.CRITICAL,
        ).count(),
    })


def tenant_public(request,slug=None):
    from tenants.models import Tenant
    if slug:
        tenant=get_object_or_404(
            Tenant,
            status=Tenant.Status.ACTIVE,
            public_enabled=True,
            public_slug=slug,
        )
    else:
        tenant=getattr(request,"tenant",None)
        if not tenant or tenant.status!=Tenant.Status.ACTIVE or not tenant.public_enabled:
            return render(request,"home.html")

    services=tenant.services.filter(active=True).order_by("name")[:50]
    professionals=tenant.professionals.filter(active=True).order_by("name")[:50]
    units=tenant.units.filter(active=True).order_by("-is_primary","name")
    public_slug=tenant.public_slug or tenant.slug
    return render(request,"tenant_public.html",{
        "tenant":tenant,
        "services":services,
        "professionals":professionals,
        "units":units,
        "public_slug":public_slug,
    })


def home(request):
    if request.user.is_authenticated:
        if request.user.tenant_id:
            return _tenant_dashboard(request)
        return _platform_dashboard(request)
    if getattr(request,"tenant",None):
        return tenant_public(request)
    return render(request,"home.html")
