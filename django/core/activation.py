"""Read-only activation status, shared by the company and platform consoles."""
from django.urls import reverse
from datetime import date,datetime
from django.utils import timezone
from billing.segment_access import segment_enabled
from core.unit_scope import scope_queryset

def activation_status(tenant, unit):
    from scheduling.models import Professional, ProfessionalAvailability, Service
    from arena.models import Court, CourtHours, PriceRule
    arena=segment_enabled(tenant,'arena')
    steps=[]
    def add(title,done,url):
        steps.append({'title':title,'done':bool(done),'url':url})
    branding=reverse('tenant-branding')+(f'?unit={unit.pk}' if unit else '')
    add('Unidade ativa',unit and unit.active,branding)
    add('Endereço completo e localização',unit and unit.postal_code and unit.address and unit.address_number and unit.city and unit.state and unit.latitude is not None and unit.longitude is not None,branding)
    add('Funcionamento da unidade',unit and unit.business_hours.filter(active=True,closed=False,opens_at__isnull=False,closes_at__isnull=False).exists(),reverse('portal-resource-list',args=['agenda','horarios-unidades']))
    if arena:
        add('Quadras ativas',unit and Court.objects.filter(tenant=tenant,unit=unit,active=True).exists(),reverse('portal-resource-list',args=['arena','quadras']))
        add('Preços de reserva',unit and scope_queryset(PriceRule.objects.filter(tenant=tenant,active=True,court__active=True),unit).exists(),reverse('portal-resource-list',args=['arena','precos']))
        add('Horários das quadras',unit and scope_queryset(CourtHours.objects.filter(tenant=tenant,active=True,court__active=True),unit).exists(),reverse('portal-resource-list',args=['arena','horarios-quadras']))
    else:
        from scheduling.availability import AvailabilityService
        staff=list(Professional.objects.filter(tenant=tenant,unit=unit,active=True)) if unit else []
        services=list(scope_queryset(Service.objects.filter(tenant=tenant,active=True),unit)) if unit else []
        add('Equipe ativa',staff,reverse('portal-resource-list',args=['agenda','profissionais']))
        add('Serviços com profissional responsável',any(AvailabilityService().professional_offers(tenant,p.pk,s.pk) for p in staff for s in services),reverse('portal-resource-list',args=['agenda','servicos']))
        add('Horários da equipe',unit and scope_queryset(ProfessionalAvailability.objects.filter(tenant=tenant,active=True,professional__active=True),unit).exists(),reverse('portal-resource-list',args=['agenda','expedientes']))
    add('Página publicada com agendamento habilitado',tenant.public_enabled and tenant.public_booking_enabled,branding)
    if unit:
        for step in steps:
            if '?unit=' not in step['url']: step['url']+=f'?unit={unit.pk}'
        opening={h.weekday:h for h in unit.business_hours.filter(active=True)}
        def window(hour):
            start,end=hour.start_time,hour.end_time
            business=opening.get(hour.weekday)
            if business:
                if business.closed or not business.opens_at or not business.closes_at: return None
                start,end=max(start,business.opens_at),min(end,business.closes_at)
            return (start,end) if end>start else None
        if arena:
            rules=list(scope_queryset(PriceRule.objects.filter(tenant=tenant,active=True,court__active=True),unit))
            hours=scope_queryset(CourtHours.objects.filter(tenant=tenant,active=True,court__active=True),unit).select_related('court')
            def compatible(hour,rule):
                interval=window(hour)
                if not interval or hour.court_id!=rule.court_id or (rule.weekday and rule.weekday!=hour.weekday): return False
                if rule.valid_to and rule.valid_to<timezone.localdate(): return False
                if rule.specific_date and (rule.specific_date<timezone.localdate() or rule.specific_date.isoweekday()!=hour.weekday): return False
                start,end=interval
                start,end=max(start,rule.start_time or start),min(end,rule.end_time or end)
                duration=max(hour.court.minimum_minutes,rule.minimum_duration_minutes or 0)
                maximum=min(hour.court.maximum_minutes,rule.maximum_duration_minutes or hour.court.maximum_minutes)
                return duration<=maximum and (datetime.combine(date.today(),end)-datetime.combine(date.today(),start)).total_seconds()/60>=duration and (not rule.modality_id or hour.court.modalities.filter(pk=rule.modality_id,active=True).exists())
            steps[5]['done']=any(compatible(h,r) for h in hours for r in rules)
            steps[5]['title']='Horários compatíveis com quadras e preços'
        else:
            hours=scope_queryset(ProfessionalAvailability.objects.filter(tenant=tenant,active=True,professional__active=True),unit)
            def usable(hour,service):
                interval=window(hour)
                return interval and AvailabilityService().professional_offers(tenant,hour.professional_id,service.pk) and (datetime.combine(date.today(),interval[1])-datetime.combine(date.today(),interval[0])).total_seconds()/60>=service.duration_minutes
            steps[5]['done']=any(usable(h,s) for h in hours for s in services)
            steps[5]['title']='Horários compatíveis com os serviços'
    completed=sum(s['done'] for s in steps)
    return {'unit':unit,'steps':steps,'completed':completed,'total':len(steps),'progress':round(completed*100/len(steps)),'ready':completed==len(steps),'pending':[s for s in steps if not s['done']]}
