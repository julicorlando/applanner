from datetime import timedelta
from uuid import UUID
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count,Avg,Max,Q
from django.shortcuts import render
from django.utils import timezone
from django.conf import settings
from core.master import _guard
from .models import RuntimeEvent,CronHeartbeat

@login_required
def dashboard(request):
    _guard(request.user)
    from communications.models import Notification
    from billing.models import WebhookEvent
    now=timezone.now();cutoff=now-timedelta(hours=24)
    threshold=getattr(settings,'OPERATION_SLOW_REQUEST_MS',2000)
    recent=RuntimeEvent.objects.filter(created_at__gte=cutoff)
    http=recent.filter(component='http')
    totals=http.aggregate(total=Count('pk'),errors=Count('pk',filter=Q(status_code__gte=500)),slow=Count('pk',filter=Q(duration_ms__gte=threshold)),average=Avg('duration_ms'),maximum=Max('duration_ms'))
    rows=RuntimeEvent.objects.filter(created_at__gte=now-timedelta(days=14)).order_by('-created_at')
    trace=request.GET.get('trace','').strip();invalid=False
    if trace:
        try: rows=rows.filter(request_id=UUID(trace))
        except ValueError: rows=rows.none();invalid=True
    if request.GET.get('failures')=='1': rows=rows.filter(status_code__gte=500)
    component=request.GET.get('component','')
    if component in {'http','notification'}: rows=rows.filter(component=component)
    page=Paginator(rows,50).get_page(request.GET.get('page'))
    params=request.GET.copy();params.pop('page',None)
    return render(request,'master/monitoring.html',{'totals':totals,'page':page,'params':params.urlencode(),'trace':trace,'invalid_trace':invalid,'slow_ms':threshold,'queue':Notification.objects.filter(status='queued',tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True).count(),'failed':Notification.objects.filter(status='failed',tenant__deleted_at__isnull=True,tenant__archived_at__isnull=True).count(),'webhooks':WebhookEvent.objects.filter(status__in=['failed','rejected']).order_by('-received_at')[:20],'heartbeats':CronHeartbeat.objects.order_by('-started_at')[:20]})
