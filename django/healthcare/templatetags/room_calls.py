import uuid
from datetime import timedelta
from django import template
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from billing.entitlements import module_enabled
from healthcare.operation_access import appointments_for
from healthcare.operation_models import WaitingRoomDisplay
from healthcare.rooms import current_room

register = template.Library()


@register.inclusion_tag('healthcare/record_call.html', takes_context=True)
def patient_tv_call(context, customer_id=None, appointment_id=None):
    request = context['request']
    user = request.user
    if not user.is_authenticated or not user.tenant_id or not module_enabled(user.tenant, 'waiting-room-tv'):
        return {}
    try:
        rows = appointments_for(user)
    except PermissionDenied:
        return {}
    if appointment_id:
        rows = rows.filter(pk=appointment_id)
    elif customer_id:
        rows = rows.filter(customer_id=customer_id)
    else:
        return {}
    now = timezone.now()
    rows = list(rows.filter(starts_at__gte=now-timedelta(hours=24), starts_at__lte=now+timedelta(hours=24),
        status__in=['pending', 'confirmed', 'waiting', 'in_progress']).order_by('starts_at')[:100])
    return {'request': request, 'csrf_token': context.get('csrf_token'), 'call_appointments': rows,
        'call_room': current_room(user), 'call_enabled': WaitingRoomDisplay.objects.filter(tenant=user.tenant, enabled=True).exists(),
        'call_request_id': uuid.uuid4(), 'show_call': True}
