"""Unit-isolated delivery status and bounded retry of failed booking notifications."""
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import CharField
from django.db.models.functions import Cast
from django.db.models.fields.json import KeyTextTransform
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.permissions import require_any_capability
from core.audit import append_audit
from core.unit_scope import selected_unit,scope_queryset
from scheduling.models import Appointment
from .portal import _tenant
from .models import Notification


def scope(request):
    require_any_capability(request.user,'communications.manage','agenda.manage','arena.manage')
    if not request.user.is_superuser and request.user.role not in {'owner','manager','tenant-admin','reception','barber-manager','arena-manager','auto-manager'}: raise PermissionDenied
    tenant=_tenant(request);unit=selected_unit(request,tenant)
    appointments=scope_queryset(Appointment.objects.filter(tenant=tenant),unit)
    # IDs are produced only by the trusted server; do not expose subscription notices.
    ids=appointments.annotate(reference=Cast('pk',CharField())).values('reference')
    qs=Notification.objects.filter(tenant=tenant,template_key__startswith='appointment_').annotate(appointment_reference=Cast(KeyTextTransform('appointment_id','payload'),CharField())).filter(appointment_reference__in=ids)
    return tenant,unit,qs


def can_retry(row):
    return (row.status=='failed' and not row.sent_at and not row.delivered_at and not row.provider_reference
        and row.channel in {'email','whatsapp'} and row.manual_retry_count<3
        and (not row.last_manual_retry_at or row.last_manual_retry_at<=timezone.now()-timedelta(minutes=5)))

def appointment_eligible(row,appointment):
    if not appointment: return False
    if row.template_key in {'appointment_feedback','appointment_rating'}:
        return appointment.status=='completed'
    if row.template_key in {'appointment_2h','appointment_24h','appointment_reminder'} and appointment.starts_at<=timezone.now():
        return False
    return appointment.status in {'pending','confirmed','waiting','in_progress'}

@login_required
def dashboard(request):
    tenant,unit,qs=scope(request)
    state=request.GET.get('status','')
    if state=='delivered': qs=qs.filter(delivered_at__isnull=False)
    elif state in dict(Notification.Status.choices): qs=qs.filter(status=state)
    page=Paginator(qs.order_by('-created_at'),50).get_page(request.GET.get('page'))
    rows=list(page.object_list)
    ids=[int(str(row.payload.get('appointment_id'))) for row in rows if str(row.payload.get('appointment_id','')).isdigit()]
    appointments=Appointment.objects.filter(tenant=tenant,pk__in=ids).in_bulk()
    for row in rows:
        raw=str(row.payload.get('appointment_id',''))
        row.retry_allowed=can_retry(row) and appointment_eligible(row,appointments.get(int(raw)) if raw.isdigit() else None)
    page.object_list=rows
    return render(request,'communications/delivery_center.html',{'tenant':tenant,'unit':unit,'page':page,'state':state,'states':Notification.Status.choices})

@login_required
@require_POST
def retry(request,pk):
    tenant,unit,qs=scope(request)
    if request.user.role=='reception' and not request.user.is_superuser: raise PermissionDenied
    with transaction.atomic():
        row=get_object_or_404(qs.select_for_update(),pk=pk)
        appointment=Appointment.objects.filter(pk=row.payload.get('appointment_id'),tenant=tenant).first()
        eligible=appointment_eligible(row,appointment)
        if not eligible or not can_retry(row):
            messages.error(request,'Esta notificação não permite reenvio. Confira o atendimento e a situação de entrega.')
        else:
            before={'status':row.status,'manual_retry_count':row.manual_retry_count}
            row.status='queued';row.manual_retry_count+=1;row.last_manual_retry_at=timezone.now();row.scheduled_at=None;row.error_message=''
            row.save(update_fields=['status','manual_retry_count','last_manual_retry_at','scheduled_at','error_message'])
            append_audit(request=request,user=request.user,tenant=tenant,action='NOTIFICATION_RETRY_QUEUED',entity_type='Notification',entity_id=row.pk,before=before,after={'status':row.status,'manual_retry_count':row.manual_retry_count,'trace_id':str(row.trace_id)})
            # The existing periodic queue sends it under the original row lock.
            messages.success(request,'Notificação colocada novamente na fila. Acompanhe a entrega nesta central.')
    return redirect('communications-deliveries')
