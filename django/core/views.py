from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.db.models import Q,Sum
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
    if request.user.role=="professional" and not request.user.is_superuser:
        from django.shortcuts import redirect
        return redirect("professional-area")
    from billing.entitlements import active_subscription,module_enabled
    from billing.segment_access import segment_enabled
    from billing.models import TenantModule
    from finance.models import FinancialTransaction
    from scheduling.models import Appointment,Customer,Professional
    from .portal import available_modules
    from accounts.permissions import has_capability

    tenant=request.user.tenant
    now=timezone.localtime()
    start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    end=start+timedelta(days=1)
    month_start=start.replace(day=1)

    today_qs=Appointment.objects.filter(
        tenant=tenant,starts_at__gte=start,starts_at__lt=end
    )
    finance_start=start if request.user.role=="reception" else month_start
    finance_transactions=FinancialTransaction.objects.filter(
        tenant=tenant,
        status=FinancialTransaction.Status.PAID,
        paid_at__gte=finance_start,
        paid_at__lt=end if request.user.role=="reception" else now+timedelta(days=1),
    )
    gross_revenue=finance_transactions.filter(type=FinancialTransaction.Type.INCOME).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    expenses=finance_transactions.filter(type=FinancialTransaction.Type.EXPENSE).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    net_revenue=gross_revenue-expenses

    modules=list(TenantModule.objects.filter(tenant=tenant,enabled=True,module__active=True)
        .select_related("module").order_by("module__sort_order","module__name"))
    subscription=active_subscription(tenant)
    if subscription:
        plan_modules=list(
            subscription.plan.module_links.filter(
                enabled=True,module__active=True
            ).select_related("module")
        )
        known={row.module_id for row in modules}
        modules.extend(row for row in plan_modules if row.module_id not in known)
    modules=[row for row in modules if module_enabled(tenant,row.module.slug)]

    from engagement.referrals import active_referral_campaign
    referral_campaign=active_referral_campaign()
    company_referral_roles={"owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager"}
    if referral_campaign and (
        request.user.role not in company_referral_roles or not referral_campaign.company_referrals_enabled
    ):
        referral_campaign=None

    available=available_modules(request.user,tenant)
    segment_module=next((item for item in available if item["slug"] in {"auto","saude","arena","barbearia"}),None)

    return_intelligence_rows=[]
    behavior_enabled=not subscription or module_enabled(tenant,"behavior")
    if behavior_enabled and request.user.role!="professional":
        from engagement.contacting import contact_blocked
        from engagement.models import BehaviorProfile
        return_horizon=timezone.localdate()+timedelta(days=14)
        return_qs=(
            BehaviorProfile.objects.filter(
                tenant=tenant,next_expected_date__isnull=False,
                next_expected_date__lte=return_horizon,
            ).select_related("customer").order_by("next_expected_date","customer__name")
        )
        return_intelligence_rows=list(return_qs[:8])
        for row in return_intelligence_rows:
            row.contact_blocked=contact_blocked(tenant,row.customer)
    arena_mode=segment_enabled(tenant,"arena")
    arena_category="arena" in (tenant.category or "").lower() or "quadra" in (tenant.category or "").lower()
    if arena_mode:
        from arena.models import Court,CourtHours,PriceRule,Reservation
        arena_today=Reservation.objects.filter(tenant=tenant,starts_at__gte=start,starts_at__lt=end)
        arena_today_total=arena_today.count()
        arena_today_pending=arena_today.filter(status__in=[
            Reservation.Status.CONFIRMED,Reservation.Status.PENDING_PAYMENT,
        ]).count()
        courts_count=Court.objects.filter(tenant=tenant,active=True).count()
        arena_has_hours=CourtHours.objects.filter(tenant=tenant,court__active=True,active=True).exists()
        arena_has_prices=PriceRule.objects.filter(tenant=tenant,court__active=True,active=True).exists()
        arena_upcoming=Reservation.objects.filter(tenant=tenant,starts_at__gte=timezone.now(),
            status__in=[Reservation.Status.CONFIRMED,Reservation.Status.PENDING_PAYMENT]
        ).select_related("court").order_by("starts_at")[:8]
    else:
        arena_upcoming=[]
        arena_today_total=arena_today_pending=courts_count=0
        arena_has_hours=arena_has_prices=False
    return render(request,"dashboard.html",{
        "tenant":tenant,
        "today_total":today_qs.count(),
        "today_pending":today_qs.filter(status__in=[
            Appointment.Status.PENDING,Appointment.Status.CONFIRMED
        ]).count(),
        "customers":Customer.objects.filter(tenant=tenant,active=True).count(),
        "professionals":Professional.objects.filter(tenant=tenant,active=True).count(),
        "revenue":net_revenue,
        "gross_revenue":gross_revenue,"expenses":expenses,"net_revenue":net_revenue,
        "next_appointments":Appointment.objects.filter(tenant=tenant,starts_at__gte=now,
            status__in=[Appointment.Status.PENDING,Appointment.Status.CONFIRMED]).select_related(
            "customer","service","professional"
        ).order_by("starts_at")[:8],
        "modules":modules,
        "available_modules":available,"segment_module":segment_module,
        "subscription":subscription,
        "can_manage_agenda":has_capability(request.user,"agenda.manage"),
        "can_manage_finance":has_capability(request.user,"finance.manage") and request.user.role!="reception",
        "can_sell_products":has_capability(request.user,"finance.manage") and request.user.role=="reception",
        "reception_mode":request.user.role=="reception",
        "revenue_period_label":"Receita líquida do dia" if request.user.role=="reception" else "Receita líquida do mês",
        "arena_mode":arena_mode,"arena_category":arena_category,
        "arena_has_hours":arena_has_hours,"arena_has_prices":arena_has_prices,
        "arena_upcoming":arena_upcoming,
        "arena_today_total":arena_today_total,"arena_today_pending":arena_today_pending,
        "courts_count":courts_count,
        "referral_campaign":referral_campaign,
        "return_intelligence_rows":return_intelligence_rows,
        "behavior_enabled":behavior_enabled,
    })


def _platform_dashboard(request):
    from billing.models import Plan, Subscription
    from commercial.models import Lead
    from operations.models import OperationalIncident, SupportTicket
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
        "plans_available":Plan.objects.filter(active=True,public_visible=True).count(),
        "tickets_open":SupportTicket.objects.exclude(status__in=[SupportTicket.Status.RESOLVED,SupportTicket.Status.CLOSED]).count(),
        "recent_leads":Lead.objects.order_by("-created_at")[:5],
        "recent_tenants":Tenant.objects.order_by("-created_at")[:5],
    })


def _public_tenant_context(tenant,professional=None):
    from billing.entitlements import active_subscription,module_enabled
    from contenthub.models import PublicReview
    from engagement.models import ServicePackage,TenantLoyaltySettings
    from finance.models import Product
    from scheduling.availability import AvailabilityService
    from scheduling.models import Appointment
    from billing.payment_services import has_connected_tenant_gateway

    services=tenant.services.filter(active=True).order_by("name")[:100]
    professionals=list(tenant.professionals.filter(active=True).prefetch_related("services").order_by("name")[:100])
    for item in professionals:
        offered=list(item.services.all())
        item.public_all_services=not item.services_restricted and not offered
        item.public_service_ids=",".join(str(service.pk) for service in offered if service.tenant_id==tenant.pk and service.active)
    if professional is not None:
        offered=professional.services.filter(tenant=tenant,active=True)
        if professional.services_restricted or professional.services.exists():
            services=offered.order_by("name")[:100]
    units=tenant.units.filter(active=True).order_by("-is_primary","name")
    active_product_appointment_statuses=[
        Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
        Appointment.Status.WAITING,Appointment.Status.IN_PROGRESS,
    ]
    products=list(
        Product.objects.filter(tenant=tenant,active=True)
        .annotate(
            reserved_stock=Sum(
                "reservations__quantity",
                filter=Q(reservations__appointment__status__in=active_product_appointment_statuses),
            )
        )
        .order_by("name")[:24]
    )
    for product in products:
        product.public_available_stock=max(
            Decimal("0"),product.stock-(product.reserved_stock or Decimal("0")),
        )
    packages=ServicePackage.objects.filter(tenant=tenant,active=True).order_by("name")[:24]
    reviews=PublicReview.objects.filter(tenant=tenant,active=True).order_by("-created_at")[:12]
    loyalty=TenantLoyaltySettings.objects.filter(tenant=tenant,enabled=True).first()
    payment_settings=AvailabilityService().settings(tenant)
    gateway_connected=payment_settings.online_booking_payments_enabled and has_connected_tenant_gateway(tenant)
    from billing.segment_access import segment_enabled
    segment=next((item for item in ("auto","saude","arena","barbearia") if segment_enabled(tenant,item)),None)
    # O tipo de negócio determina o conteúdo público; o direito de reservar
    # continua sujeito ao módulo contratado e é verificado também pela API.
    if not segment and ("arena" in (tenant.category or "").lower() or "quadra" in (tenant.category or "").lower()):
        segment="arena"
    arena_access_enabled=segment=="arena" and segment_enabled(tenant,"arena")
    courts=tenant.sports_courts.filter(active=True).order_by("sort_order","name")[:24] if segment=="arena" else []
    if arena_access_enabled:
        from arena.public import _deposit_available
        arena_deposit_available=_deposit_available(tenant)
    else:
        arena_deposit_available=False
    wording={"auto":("AGENDAMENTO AUTOMOTIVO","Escolha o serviço para seu veículo e um horário disponível.","Veículo e serviço"),
        "saude":("AGENDAMENTO DE SAÚDE","Escolha seu atendimento e um profissional disponível.","Atendimento"),
        "arena":("RESERVA NA ARENA","Escolha a atividade e um horário disponível.","Atividade"),
        "barbearia":("AGENDAMENTO NA BARBEARIA","Escolha o serviço e o profissional para seu atendimento.","Serviço")}
    return {
        "tenant":tenant,"services":services,"professionals":professionals,"units":units,
        "products":products,"packages":packages,"reviews":reviews,"loyalty":loyalty,
        "public_slug":tenant.public_slug or tenant.slug,"selected_professional":professional,
        "waitlist_enabled":not active_subscription(tenant) or module_enabled(tenant,"waitlist"),
        "payment_settings":payment_settings,"online_payment_available":gateway_connected,
        "online_payment_choices":gateway_connected and (payment_settings.allow_partial_payment or payment_settings.allow_full_payment),
        "booking_payment_available":payment_settings.allow_pay_on_site or (gateway_connected and (payment_settings.allow_partial_payment or payment_settings.allow_full_payment)),
        "segment":segment,"booking_wording":wording.get(segment,("AGENDAMENTO ONLINE","Escolha serviço, profissional e horário.","Serviço")),
        "courts":courts,
        "arena_deposit_available":arena_deposit_available,
        "arena_access_enabled":arena_access_enabled,
    }


def tenant_public(request,slug=None):
    from tenants.models import Tenant
    if slug:
        tenant=get_object_or_404(
            Tenant.objects.filter(Q(public_slug=slug)|Q(public_slug__isnull=True,slug=slug)),
            status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],
            public_enabled=True,deleted_at__isnull=True,
        )
    else:
        tenant=getattr(request,"tenant",None)
        if not tenant or tenant.status not in [Tenant.Status.TRIAL,Tenant.Status.ACTIVE] or not tenant.public_enabled:
            return render(request,"home.html")
    return render(request,"tenant_public.html",_public_tenant_context(tenant))


def professional_public(request,slug,professional_slug):
    from scheduling.models import Professional
    from tenants.models import Tenant
    tenant=get_object_or_404(
        Tenant.objects.filter(Q(public_slug=slug)|Q(public_slug__isnull=True,slug=slug)),
        status__in=[Tenant.Status.TRIAL,Tenant.Status.ACTIVE],
        public_enabled=True,deleted_at__isnull=True,
    )
    professional=get_object_or_404(
        Professional,tenant=tenant,active=True,public_slug=professional_slug,
    )
    return render(
        request,"tenant_public.html",_public_tenant_context(tenant,professional=professional)
    )


def home(request):
    if request.user.is_authenticated:
        if request.user.tenant_id:
            return _tenant_dashboard(request)
        return _platform_dashboard(request)
    if getattr(request,"tenant",None):
        return tenant_public(request)
    from billing.models import Plan
    from contenthub.models import BlogPost,FAQItem,PlatformHomepage
    platform=PlatformHomepage.objects.order_by("pk").first()
    medical_visible=bool(platform and platform.medical_segment_visible)
    plans_qs=Plan.objects.filter(active=True,public_visible=True,is_custom=False)
    if not medical_visible:
        plans_qs=plans_qs.exclude(slug="segment-medico")
    plans=plans_qs.order_by("sort_order","name")[:4]
    medical_plan=(Plan.objects.filter(slug="segment-medico").first() if medical_visible else None)
    posts=BlogPost.objects.filter(status=BlogPost.Status.PUBLISHED).order_by("-featured","-published_at","-created_at")[:3]
    faqs=FAQItem.objects.filter(active=True).order_by("sort_order","id")[:24]
    return render(request,"home.html",{
        "plans":plans,"medical_plan":medical_plan,"posts":posts,"faqs":faqs,
        "medical_segment_visible":medical_visible,
    })
