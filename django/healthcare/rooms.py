"""Daily room choice is scoped to the authenticated operator and clinic."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from billing.entitlements import require_module
from core.audit import append_audit
from .operation_access import operator, ADMIN
from .operation_models import ClinicRoom, DailyRoomSelection


def room_day(user):
    try:
        zone = ZoneInfo(user.tenant.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        zone = timezone.get_default_timezone()
    return timezone.localdate(timezone=zone)


def current_selection(user):
    return DailyRoomSelection.objects.select_related('room').filter(
        tenant_id=user.tenant_id, user=user, day=room_day(user)).first()


def current_room(user):
    choice = current_selection(user)
    if choice and not choice.finished and choice.room and choice.room.active and choice.room.tenant_id == user.tenant_id:
        return choice.room
    return None


def return_to(request):
    target = request.POST.get('next', '')
    if target.startswith('/app/') and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return reverse('waiting-room-console')


@login_required
@require_POST
@never_cache
@transaction.atomic
def select_room(request):
    tenant = operator(request.user)
    require_module(tenant, 'waiting-room-tv')
    if request.POST.get('action') == 'finish':
        room = None
        finished = True
    else:
        pk = request.POST.get('room', '')
        if not pk.isdigit():
            return HttpResponse('Escolha uma sala cadastrada.', status=400)
        room = get_object_or_404(ClinicRoom, pk=pk, tenant=tenant, active=True)
        finished = False
    # Serialize concurrent choices by the same account (including first access of the day).
    get_user_model().objects.select_for_update(of=('self',)).get(pk=request.user.pk)
    row, _ = DailyRoomSelection.objects.update_or_create(tenant=tenant, user=request.user,
        day=room_day(request.user), defaults={'room': room, 'finished': finished})
    append_audit(tenant=tenant, user=request.user, request=request, action='tv.room.day_finished' if finished else 'tv.room.selected',
        entity_type='DailyRoomSelection', entity_id=row.pk, after={'room_id': room.pk if room else None})
    messages.success(request, 'Dia finalizado. Se voltar a atender, escolha uma sala.' if finished else f'Sala de hoje: {room.name}.')
    return redirect(return_to(request))


@login_required
@require_POST
@never_cache
@transaction.atomic
def manage_room(request):
    tenant = operator(request.user)
    require_module(tenant, 'waiting-room-tv')
    if request.user.role not in ADMIN:
        raise PermissionDenied
    action = request.POST.get('action')
    if action == 'create':
        name = ' '.join(request.POST.get('name', '').split())
        if not 1 <= len(name) <= 60:
            return HttpResponse('Informe um nome de sala de até 60 caracteres.', status=400)
        room, created = ClinicRoom.objects.get_or_create(tenant=tenant, name=name)
        if not created:
            return HttpResponse('Esta sala já está cadastrada. Você pode reativá-la.', status=409)
    elif action in {'activate', 'deactivate'}:
        pk = request.POST.get('room', '')
        if not pk.isdigit():
            return HttpResponse('Sala inválida.', status=400)
        room = get_object_or_404(ClinicRoom.objects.select_for_update(), tenant=tenant, pk=pk)
        room.active = action == 'activate'
        room.save(update_fields=['active', 'updated_at'])
    else:
        return HttpResponse('Ação inválida.', status=400)
    append_audit(tenant=tenant, user=request.user, request=request, action=f'tv.room.{action}', entity_type='ClinicRoom', entity_id=room.pk)
    return redirect('waiting-room-console')


def room_context(request):
    if not request.path.startswith('/app/') or not request.user.is_authenticated:
        return {}
    from billing.entitlements import module_enabled
    try:
        tenant = operator(request.user)
    except PermissionDenied:
        return {}
    if not module_enabled(tenant, 'waiting-room-tv'):
        return {}
    rooms = list(ClinicRoom.objects.filter(tenant=tenant, active=True))
    selection = current_selection(request.user)
    room = current_room(request.user)
    return {'daily_room_tools': True, 'daily_rooms': rooms, 'daily_room': room,
        'daily_room_prompt': bool(rooms and not room and not (selection and selection.finished)),
        'daily_rooms_admin': request.user.role in ADMIN}
