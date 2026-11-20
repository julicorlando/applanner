"""Small operational history: route names and correlation IDs, never request contents."""
import logging
import time
from contextvars import ContextVar
from uuid import uuid4
from django.db import transaction
from django.utils import timezone
from django.conf import settings

request_trace=ContextVar('applanner_request_trace',default=None)
logger=logging.getLogger('applanner.operations')

def trace_id(): return request_trace.get() or uuid4()

def record_event(*,request_id,component,operation,status_code=200,duration_ms=0,error_type='',tenant_id=None):
    from .models import RuntimeEvent
    try:
        with transaction.atomic():
            RuntimeEvent.objects.create(request_id=request_id,component=component,operation=operation[:120],status_code=status_code,duration_ms=max(0,int(duration_ms)),error_type=error_type[:100],tenant_id=tenant_id)
        if status_code>=500 or duration_ms>=getattr(settings,'OPERATION_SLOW_REQUEST_MS',2000):
            logger.warning('operation request_id=%s component=%s route=%s status=%s duration_ms=%s error_type=%s',request_id,component,operation,status_code,int(duration_ms),error_type)
    except Exception as exc:
        logger.warning('Operational history unavailable request_id=%s component=%s error_type=%s',request_id,component,type(exc).__name__)

class RuntimeMonitoringMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def process_exception(self,request,exception): request.operation_error_type=type(exception).__name__
    def __call__(self,request):
        rid=uuid4();request.operation_request_id=rid
        token=request_trace.set(rid);start=time.monotonic()
        try:
            response=self.get_response(request)
            response['X-Request-ID']=str(rid)
            match=getattr(request,'resolver_match',None)
            route=getattr(match,'url_name',None) or 'unmatched'
            if not request.path.startswith(('/static/','/imagens/')) and route not in {'healthz','master-runtime-monitor'}:
                tenant=getattr(request,'tenant',None)
                user=getattr(request,'user',None)
                tenant_id=getattr(tenant,'pk',None) or getattr(user,'tenant_id',None)
                record_event(request_id=rid,component='http',operation=route,status_code=response.status_code,duration_ms=(time.monotonic()-start)*1000,error_type=getattr(request,'operation_error_type',''),tenant_id=tenant_id)
                if user and user.is_authenticated and user.tenant_id and not user.is_superuser and not request.session.get('support_access_id') and request.path.startswith('/app/') and 200<=response.status_code<400:
                    from .models import TenantActivity
                    from datetime import timedelta
                    try:
                        with transaction.atomic():
                            row,created=TenantActivity.objects.get_or_create(tenant_id=user.tenant_id,defaults={'last_active_at':timezone.now()})
                            if not created and row.last_active_at<timezone.now()-timedelta(minutes=5):
                                TenantActivity.objects.filter(pk=row.pk,last_active_at__lt=timezone.now()-timedelta(minutes=5)).update(last_active_at=timezone.now())
                    except Exception as exc: logger.warning('Account activity unavailable: %s',type(exc).__name__)
            return response
        finally: request_trace.reset(token)
