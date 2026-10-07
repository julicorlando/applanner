"""A master-controlled presentation; existing permissions and business flows stay authoritative."""
from zoneinfo import ZoneInfo
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404,redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.permissions import has_capability
from tenants.models import Tenant
from .audit import append_audit


@login_required
@require_POST
@transaction.atomic
def set_mode(request,pk):
    if not request.user.is_superuser:raise PermissionDenied('Somente o Master pode alterar o modo simples.')
    action=request.POST.get('action')
    if action not in {'enable','disable'}:return HttpResponseBadRequest('Escolha ativar ou desativar.')
    tenant=get_object_or_404(Tenant.objects.select_for_update(),pk=pk,deleted_at__isnull=True,archived_at__isnull=True)
    enabled=action=='enable';before=tenant.simple_mode
    if before!=enabled:
        tenant.simple_mode=enabled;tenant.save(update_fields=['simple_mode','updated_at'])
        append_audit(request=request,user=request.user,tenant=tenant,action='MASTER_COMPANY_SIMPLE_MODE',
            entity_type='tenants.Tenant',entity_id=tenant.pk,before={'simple_mode':before},after={'simple_mode':enabled})
    messages.success(request,('Modo simples ativado para ' if enabled else 'Modo simples desativado para ')+tenant.name+'.')
    if request.POST.get('destination')=='detail':return redirect('master-company-detail',pk=tenant.pk)
    return redirect('master-resource-list',slug='empresas')


def navigation(request,tenant,modules=None):
    cached=getattr(request,'_simple_company_navigation',None)
    if cached is not None:return cached
    from .portal import available_modules
    modules=modules if modules is not None else available_modules(request.user,tenant)
    routes={(m['slug'],r['slug']) for m in modules for r in m['resources']}
    cards=[]
    definitions=[('agenda','agendamentos','Agenda','Veja os horários, clientes e barbeiros.','◷'),
        ('agenda','clientes','Clientes','Encontre os contatos e o histórico dos seus clientes.','◉'),
        ('agenda','servicos','Serviços e preços','Cadastre corte, barba e outros serviços.','✂'),
        ('agenda','profissionais','Minha equipe','Cadastre os profissionais que atendem na unidade.','👥'),
        ('arena','reservas','Reservas','Veja as reservas e os horários das quadras.','◷'),
        ('arena','quadras','Quadras','Organize os espaços disponíveis para reserva.','▦')]
    for module,resource,title,description,icon in definitions:
        if (module,resource) in routes:
            cards.append({'title':title,'description':description,'icon':icon,'url':reverse('portal-resource-list',args=[module,resource])})
    from billing.segment_access import segment_enabled
    booking=('arena','reservas') if segment_enabled(tenant,'arena') else ('agenda','agendamentos')
    if booking in routes:
        from .portal import PORTAL_MODULES,_role_resource_write
        if _role_resource_write(request.user,*booking) and (PORTAL_MODULES[booking[0]]['resources'][booking[1]].get('create',True) or PORTAL_MODULES[booking[0]]['resources'][booking[1]].get('custom_create')):
            cards.insert(0,{'title':'Nova reserva' if booking[0]=='arena' else 'Novo agendamento','description':'Escolha o cliente, o serviço e o horário.','icon':'+','url':reverse('portal-resource-create',args=booking),'primary':True})
    if ('comunicacao','whatsapp') in routes:
        cards.append({'title':'WhatsApp','description':'Veja as conversas e acompanhe o atendimento.','icon':'✉','url':reverse('communications-inbox')})
    nav=[{'title':'Início','url':reverse('portal-home')}]
    if request.user.role=='professional':nav.append({'title':'Minha agenda','url':reverse('professional-area')})
    else:nav.extend({'title':c['title'],'url':c['url']} for c in cards if c['title'] in {'Agenda','Clientes','Reservas'})
    result={'simple_mode':True,'simple_cards':cards,'simple_nav':nav,'simple_modules':modules,
        'simple_can_manage':request.user.is_superuser or request.user.role in {'owner','manager','tenant-admin','barber-manager','arena-manager','auto-manager'},'simple_company':tenant}
    request._simple_company_navigation=result
    return result


def company_context(request):
    user=getattr(request,'user',None)
    if not user or not user.is_authenticated or not request.path.startswith(('/app/','/account/','/billing/')):return {}
    if user.is_superuser:
        if not request.path.startswith('/app/'):return {}
        tenant=Tenant.objects.filter(pk=request.session.get('portal_tenant_id'),deleted_at__isnull=True,archived_at__isnull=True).first()
    else:tenant=user.tenant if user.tenant_id else None
    if not tenant or not tenant.simple_mode:return {}
    if getattr(request,'billing_locked',False):return {'simple_mode':True,'simple_nav':[]}
    return navigation(request,tenant)


def dashboard_context(request,tenant,modules):
    from .unit_scope import selected_unit,scope_queryset
    from .operation_insights import day_bounds
    from billing.segment_access import segment_enabled
    unit=selected_unit(request,tenant)
    day=timezone.now().astimezone(ZoneInfo(tenant.timezone or 'America/Recife')).date()
    start,end=day_bounds(tenant,day);arena=segment_enabled(tenant,'arena')
    data={'tenant':tenant,'unit':unit,'day':day,'simple_rows':[],'simple_total':None,'simple_completed':0,**navigation(request,tenant,modules)}
    if has_capability(request.user,'arena.manage' if arena else 'agenda.manage'):
        if arena:
            from arena.models import Reservation
            rows=scope_queryset(Reservation.objects.filter(tenant=tenant,starts_at__gte=start,starts_at__lt=end),unit).select_related('court','customer')
        else:
            from scheduling.models import Appointment
            rows=scope_queryset(Appointment.objects.filter(tenant=tenant,starts_at__gte=start,starts_at__lt=end),unit).select_related('customer','professional','service')
        data.update(simple_total=rows.exclude(status='cancelled').count(),simple_completed=rows.filter(status='completed').count(),simple_rows=list(rows.exclude(status__in=['cancelled','completed','no_show']).order_by('starts_at')[:5]),arena=arena)
    return data
