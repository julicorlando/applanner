"""Daily actions, schedule utilization and tenant-isolated customer timeline."""
from collections import Counter
from datetime import datetime,timedelta,time,date
from decimal import Decimal
from zoneinfo import ZoneInfo
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.db.models import Q,Sum
from django.shortcuts import render,redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.permissions import require_any_capability,has_capability
from billing.entitlements import module_enabled
from billing.segment_access import segment_enabled
from scheduling.models import Appointment,Customer,Professional,ProfessionalAvailability,ProfessionalBreak,ProfessionalTimeOff
from scheduling.settlement import settle_appointment
from finance.platform_dashboard import PeriodForm
from .portal import _require_tenant
from .unit_scope import selected_unit,scope_queryset
from .audit import append_audit


def context(request):
    tenant=_require_tenant(request)
    if not tenant: return None,None
    require_any_capability(request.user,'arena.manage' if segment_enabled(tenant,'arena') else 'agenda.manage')
    return tenant,selected_unit(request,tenant)


def day_bounds(tenant,day):
    tz=ZoneInfo(tenant.timezone or 'America/Recife')
    return datetime.combine(day,time.min,tz),datetime.combine(day+timedelta(days=1),time.min,tz)

@login_required
def today(request):
    tenant,unit=context(request)
    if not tenant: return redirect('portal-home')
    now=timezone.now()
    day=now.astimezone(ZoneInfo(tenant.timezone or 'America/Recife')).date()
    actual_day=day
    if request.GET.get('date'):
        try:
            chosen=date.fromisoformat(request.GET['date'])
            if not 1900 <= chosen.year <= 2100: raise ValueError
            day=chosen
        except ValueError: messages.error(request,'Escolha uma data válida para consultar a agenda.')
    week_start=day-timedelta(days=day.weekday())
    week_days=[week_start+timedelta(days=i) for i in range(7)]
    start,end=day_bounds(tenant,day)
    arena=segment_enabled(tenant,'arena')
    if arena:
        from arena.models import Reservation
        rows=list(scope_queryset(Reservation.objects.filter(tenant=tenant,starts_at__gte=start,starts_at__lt=end),unit).select_related('customer','court').order_by('starts_at'))
    else:
        rows=list(scope_queryset(Appointment.objects.filter(tenant=tenant,starts_at__gte=start,starts_at__lt=end),unit).select_related('customer','professional','service').order_by('starts_at'))
    for row in rows:
        row.late=row.starts_at<now and row.status in {'pending','confirmed','pending_payment'}
        row.can_start=row.starts_at<=now and row.status in {'pending','confirmed','waiting'}
        row.can_finish=row.starts_at<=now and row.status in {'pending','confirmed','waiting','in_progress'}
    queue=[]
    if day==actual_day and not arena and segment_enabled(tenant,'barbearia') and has_capability(request.user,'barber.manage'):
        from barber.models import BarberQueueEntry
        queue=BarberQueueEntry.objects.filter(tenant=tenant,status__in=['waiting','called','in_service']).filter(
            Q(assigned_professional__unit=unit)|Q(assigned_professional__isnull=True,preferred_professional__unit=unit)|
            Q(assigned_professional__isnull=True,preferred_professional__isnull=True,service__unit=unit)).select_related('service')[:50]
    counts=Counter(row.status for row in rows)
    return render(request,'portal/today.html',{'tenant':tenant,'unit':unit,'rows':rows,'queue':queue,'day':day,'actual_day':actual_day,'week_days':week_days,'arena':arena,
        'total':len(rows),'late':sum(r.late for r in rows),'waiting':counts['waiting'],'progress':counts['in_progress'],'completed':counts['completed']})

@login_required
@require_POST
def appointment_action(request,pk):
    tenant,unit=context(request)
    if not tenant: raise PermissionDenied
    action=request.POST.get('action')
    try:
        with transaction.atomic():
            row=get_object_or_404(scope_queryset(Appointment.objects.select_for_update().filter(tenant=tenant),unit),pk=pk)
            before={'status':row.status}
            if row.status not in {'pending','confirmed','waiting','in_progress'}:
                raise ValidationError('Este atendimento já foi encerrado ou cancelado.')
            if action in {'complete','no_show'}:
                if not row.professional_id: raise ValidationError('Defina o profissional antes de finalizar.')
                settle_appointment(appointment_id=row.pk,professional=row.professional,user=request.user,
                    attended=action=='complete',payment_method=request.POST.get('payment_method',''))
                row.refresh_from_db()
            elif action=='check_in' and row.status in {'pending','confirmed'}:
                row.status='waiting';row.checked_in_at=row.checked_in_at or timezone.now()
                row.save(update_fields=['status','checked_in_at','updated_at'])
            elif action=='start' and row.status in {'pending','confirmed','waiting'}:
                if row.starts_at>timezone.now(): raise ValidationError('Aguarde o horário de início do atendimento.')
                row.status='in_progress';row.service_started_at=row.service_started_at or timezone.now()
                row.save(update_fields=['status','service_started_at','updated_at'])
            else: raise ValidationError('Ação indisponível para a situação atual. Atualize o painel.')
            append_audit(request=request,user=request.user,action='OPERATION_TODAY_ACTION',entity_type='Appointment',entity_id=row.pk,tenant=tenant,before=before,after={'status':row.status})
    except ValidationError as exc: messages.error(request,' '.join(exc.messages))
    else: messages.success(request,'Atendimento atualizado.')
    return redirect('operation-today')


def merge(intervals):
    result=[]
    for a,b in sorted(intervals):
        if b<=a: continue
        if result and a<=result[-1][1]: result[-1]=(result[-1][0],max(b,result[-1][1]))
        else: result.append((a,b))
    return result


def subtract(windows,blocks):
    result=merge(windows)
    for a,b in merge(blocks):
        remaining=[]
        for x,y in result:
            if b<=x or a>=y: remaining.append((x,y));continue
            if x<a: remaining.append((x,a))
            if b<y: remaining.append((b,y))
        result=remaining
    return result


def minutes(intervals): return sum((b-a).total_seconds()/60 for a,b in merge(intervals))


def utilization(tenant,resource,start,end,rows,arena=False):
    """Union of booked minutes within configured opening time, less breaks/time off."""
    tz=ZoneInfo(tenant.timezone or 'America/Recife')
    if arena:
        hours=list(resource.hours.filter(tenant=tenant,active=True));breaks=[]
        blocks=list(resource.blocks.filter(tenant=tenant,status='active',ends_at__gt=day_bounds(tenant,start)[0],starts_at__lt=day_bounds(tenant,end)[1]))
    else:
        hours=list(resource.availability.filter(tenant=tenant,active=True))
        breaks=list(resource.breaks.filter(tenant=tenant,active=True))
        blocks=list(resource.time_off.filter(tenant=tenant,status='active',ends_at__gt=day_bounds(tenant,start)[0],starts_at__lt=day_bounds(tenant,end)[1]))
    unit_hours={h.weekday:h for h in resource.unit.business_hours.filter(active=True)} if resource.unit_id else {}
    available=[]
    day=start
    while day<=end:
        windows=[(datetime.combine(day,h.start_time,tz),datetime.combine(day,h.end_time,tz)) for h in hours if h.weekday==day.isoweekday()]
        opening=unit_hours.get(day.isoweekday())
        if opening:
            if opening.closed or not opening.opens_at or not opening.closes_at: windows=[]
            else:
                a,b=datetime.combine(day,opening.opens_at,tz),datetime.combine(day,opening.closes_at,tz)
                windows=[(max(x,a),min(y,b)) for x,y in windows if min(y,b)>max(x,a)]
        exclusions=[(datetime.combine(day,h.start_time,tz),datetime.combine(day,h.end_time,tz)) for h in breaks if h.weekday==day.isoweekday()]
        available.extend(subtract(windows,exclusions+[(h.starts_at,h.ends_at) for h in blocks]))
        day+=timedelta(days=1)
    booked=[(r.starts_at,r.ends_at) for r in rows if r.status not in {'cancelled','no_show','pending_payment'}]
    occupied=[(max(a,x),min(b,y)) for a,b in available for x,y in booked if min(b,y)>max(a,x)]
    capacity=minutes(available);busy=minutes(occupied)
    return {'capacity_minutes':capacity,'occupied_minutes':busy,'capacity':round(capacity/60,1),'occupied':round(busy/60,1),'occupancy':round(busy*100/capacity,1) if capacity else None}


def performance_rows(tenant,resources,start,end,arena=False):
    from arena.models import Reservation
    model=Reservation if arena else Appointment
    relation='court_id' if arena else 'professional_id'
    lower,upper=day_bounds(tenant,start)[0],day_bounds(tenant,end)[1]
    all_rows=list(model.objects.filter(tenant=tenant,**{relation+'__in':[r.pk for r in resources]},starts_at__gte=lower,starts_at__lt=upper).select_related('customer',*(['court'] if arena else ['service'])))
    prior=set(model.objects.filter(tenant=tenant,status='completed',starts_at__lt=lower).exclude(customer_id=None).values_list('customer_id',flat=True))
    result=[]
    for resource in resources:
        rows=[r for r in all_rows if getattr(r,relation)==resource.pk]
        completed=[r for r in rows if r.status=='completed']
        amount=sum((r.total_amount if arena else r.service_price_snapshot if r.service_price_snapshot is not None else r.service.price for r in completed),Decimal('0'))
        seen=set(prior);returning=set();served=set()
        for row in sorted(completed,key=lambda r:r.starts_at):
            if row.customer_id:
                if row.customer_id in seen: returning.add(row.customer_id)
                seen.add(row.customer_id);served.add(row.customer_id)
        result.append({'name':resource.name,'unit':resource.unit,'count':len(rows),'completed':len(completed),
            'cancelled':sum(r.status=='cancelled' for r in rows),'no_show':sum(r.status=='no_show' for r in rows),
            'service_value':amount,'ticket':amount/len(completed) if completed else Decimal('0'),
            'return_rate':round(len(returning)*100/len(served),1) if served else None,
            **utilization(tenant,resource,start,end,rows,arena)})
    return result

@login_required
def performance(request):
    tenant,unit=context(request)
    if not tenant: return redirect('portal-home')
    if not request.user.is_superuser and request.user.role not in {'owner','manager','tenant-admin','barber-manager','arena-manager','auto-manager'}:
        raise PermissionDenied('Indicadores disponíveis à gestão.')
    today=timezone.now().astimezone(ZoneInfo(tenant.timezone or 'America/Recife')).date()
    form=PeriodForm(request.GET if 'start' in request.GET or 'end' in request.GET else None,initial={'start':today.replace(day=1),'end':today})
    rows=[];units=[]
    if not form.is_bound or form.is_valid():
        start,end=(form.cleaned_data['start'],form.cleaned_data['end']) if form.is_bound else (today.replace(day=1),today)
        if (end-start).days>366: form.add_error(None,'Escolha um período de até 366 dias.')
        else:
            arena=segment_enabled(tenant,'arena')
            from arena.models import Court
            model=Court if arena else Professional
            resources=list(scope_queryset(model.objects.filter(tenant=tenant,active=True),unit).select_related('unit'))
            rows=performance_rows(tenant,resources,start,end,arena)
            for location in tenant.units.filter(active=True):
                members=list(model.objects.filter(tenant=tenant,unit=location,active=True).select_related('unit'))
                data=performance_rows(tenant,members,start,end,arena)
                cap=sum(r['capacity_minutes'] for r in data);busy=sum(r['occupied_minutes'] for r in data)
                units.append({'name':location.name,'count':sum(r['count'] for r in data),'completed':sum(r['completed'] for r in data),
                    'cancelled':sum(r['cancelled'] for r in data),'no_show':sum(r['no_show'] for r in data),
                    'service_value':sum((r['service_value'] for r in data),Decimal('0')),
                    'occupancy':round(busy*100/cap,1) if cap else None})
    return render(request,'portal/performance.html',{'tenant':tenant,'unit':unit,'form':form,'rows':rows,'units':units})

class PreferenceForm(forms.Form):
    preferences=forms.CharField(label='Preferências de atendimento',max_length=1000,required=False,
        widget=forms.Textarea(attrs={'rows':3,'maxlength':1000}))

@login_required
def customer_history(request,pk):
    tenant,unit=context(request)
    if not tenant: return redirect('portal-home')
    customer=get_object_or_404(Customer,pk=pk,tenant=tenant)
    form=PreferenceForm(request.POST if request.method=='POST' else None,initial={'preferences':customer.preferences})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            customer=Customer.objects.select_for_update().get(pk=pk,tenant=tenant)
            before={'preferences':customer.preferences}
            customer.preferences=form.cleaned_data['preferences']
            customer.save(update_fields=['preferences','updated_at'])
            append_audit(request=request,user=request.user,action='CUSTOMER_PREFERENCES_UPDATED',entity_type='Customer',entity_id=customer.pk,tenant=tenant,before=before,after={'preferences':customer.preferences})
        messages.success(request,'Preferências atualizadas.')
        return redirect('customer-history',pk=pk)
    events=[]
    arena=segment_enabled(tenant,'arena')
    if arena:
        from arena.models import Reservation
        visits=Reservation.objects.filter(tenant=tenant,customer=customer).select_related('court').order_by('-starts_at')[:100]
        for row in visits: events.append({'at':row.starts_at,'kind':'Reserva','description':row.court.name,'status':row.get_status_display(),'amount':row.total_amount})
    else:
        visits=Appointment.objects.filter(tenant=tenant,customer=customer).select_related('service','professional','unit').order_by('-starts_at')[:100]
        for row in visits: events.append({'at':row.starts_at,'kind':'Atendimento','description':f'{row.service.name} · {row.professional.name if row.professional else "Sem profissional"} · {row.unit.name if row.unit else "Sem unidade"}', 'status':row.get_status_display(),'amount':row.service_price_snapshot})
    if has_capability(request.user,'finance.manage') and module_enabled(tenant,'products'):
        from finance.models import Sale
        for row in Sale.objects.filter(tenant=tenant,customer=customer).order_by('-created_at')[:100]:
            events.append({'at':row.created_at,'kind':'Compra','description':'Venda de produtos','status':row.get_status_display(),'amount':row.total})
    if has_capability(request.user,'engagement.manage') and module_enabled(tenant,'packages'):
        from engagement.models import CustomerPackage
        for row in CustomerPackage.objects.filter(tenant=tenant,customer=customer).select_related('package').order_by('-purchased_at')[:100]:
            events.append({'at':row.purchased_at,'kind':'Pacote','description':row.package.name,'status':row.get_status_display(),'amount':row.purchase_amount})
    events.sort(key=lambda row:row['at'],reverse=True)
    return render(request,'portal/customer_history.html',{'tenant':tenant,'customer':customer,'form':form,'events':events[:200]})
