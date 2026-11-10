"""Anonymous unit-level booking funnel. Only the booking server records conversions."""
import json
from uuid import uuid4
from datetime import timedelta
from django.core.cache import cache
from django.core import signing
from django.db.models import Count,Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone
from accounts.permissions import require_any_capability
from tenants.models import Tenant,Unit
from .models import BookingFunnelEvent

STAGES=[('visit','Visitas'),('resource','Serviço ou quadra selecionada'),('slot','Horário selecionado'),('confirmed','Reservas registradas')]

def record(request,tenant,unit,stage):
    if not unit or unit.tenant_id!=tenant.pk or not unit.active: return
    session=request.session
    from zoneinfo import ZoneInfo
    day=timezone.now().astimezone(ZoneInfo(tenant.timezone or 'America/Recife')).date().isoformat()
    key=f'booking_journey_{tenant.pk}'
    current=session.get(key,{})
    if current.get('day')!=day:
        current={'day':day,'id':str(uuid4())};session[key]=current
    # Every later step belongs to a visit, including direct API reservations.
    for value in ['visit',stage]:
        BookingFunnelEvent.objects.get_or_create(tenant=tenant,unit=unit,journey=current['id'],stage=value)

def page_tracking(request,tenant,unit):
    if not unit: return {}
    record(request,tenant,unit,'visit')
    return {'funnel_token':signing.dumps({'tenant':tenant.pk,'unit':unit.pk},salt='booking-funnel')}

@require_POST
def track(request,slug):
    tenant=get_object_or_404(Tenant.objects.filter(Q(public_slug=slug)|Q(public_slug__isnull=True,slug=slug)),public_enabled=True,public_booking_enabled=True,deleted_at__isnull=True,archived_at__isnull=True,status__in=['trial','active'])
    try:
        data=json.loads(request.body)
        token=signing.loads(data['token'],salt='booking-funnel',max_age=86400)
        if token['tenant']!=tenant.pk or data['stage'] not in {'visit','resource','slot'}: raise ValueError
        unit=Unit.objects.get(tenant=tenant,pk=token['unit'],active=True)
    except (ValueError,TypeError,KeyError,AttributeError,signing.BadSignature,Unit.DoesNotExist):
        return JsonResponse({'detail':'Etapa inválida.'},status=400)
    key='funnel-rate:'+str(request.session.session_key or '')+':'+str(tenant.pk)
    count=cache.get(key,0)
    if count>=40: return JsonResponse({'detail':'Limite de registros atingido.'},status=429)
    cache.set(key,count+1,60)
    record(request,tenant,unit,data['stage'])
    return JsonResponse({'ok':True})

@login_required
def dashboard(request):
    from .portal import _require_tenant
    from .unit_scope import selected_unit
    from billing.segment_access import segment_enabled
    from finance.platform_dashboard import PeriodForm
    from django.core.exceptions import PermissionDenied
    tenant=_require_tenant(request)
    if not tenant: raise PermissionDenied
    require_any_capability(request.user,'arena.manage' if segment_enabled(tenant,'arena') else 'agenda.manage')
    if not request.user.is_superuser and request.user.role not in {'owner','manager','tenant-admin','barber-manager','arena-manager','auto-manager'}: raise PermissionDenied
    unit=selected_unit(request,tenant)
    today=timezone.localdate()
    form=PeriodForm(request.GET if 'start' in request.GET or 'end' in request.GET else None,initial={'start':today-timedelta(days=29),'end':today})
    rows=[]
    if not form.is_bound or form.is_valid():
        start,end=(form.cleaned_data['start'],form.cleaned_data['end']) if form.is_bound else (today-timedelta(days=29),today)
        if (end-start).days>366: form.add_error(None,'Escolha um período de até 366 dias.')
        else:
            from .operation_insights import day_bounds
            lower,upper=day_bounds(tenant,start)[0],day_bounds(tenant,end)[1]
            for location in tenant.units.filter(active=True).order_by('name'):
                events=BookingFunnelEvent.objects.filter(tenant=tenant,unit=location,created_at__gte=lower,created_at__lt=upper)
                counts={x['stage']:x['total'] for x in events.values('stage').annotate(total=Count('journey',distinct=True))}
                visits=counts.get('visit',0)
                rows.append({'unit':location,'stages':[{'label':label,'count':counts.get(stage,0),'rate':round(counts.get(stage,0)*100/visits,1) if visits else None} for stage,label in STAGES]})
    return render(request,'portal/booking_funnel.html',{'tenant':tenant,'unit':unit,'form':form,'rows':rows})
