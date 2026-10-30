from contextvars import ContextVar

_current_tenant=ContextVar("current_tenant",default=None)


def get_current_tenant():
    return _current_tenant.get()


def _tenant_from_host(request):
    host=request.get_host().split(":",1)[0].lower().rstrip(".")
    if not host or host in {"localhost","127.0.0.1"}:
        return None
    from engagement.models import TenantDomain
    row=TenantDomain.objects.select_related("tenant").filter(
        domain__iexact=host,status=TenantDomain.Status.VERIFIED,
        tenant__public_enabled=True,
    ).first()
    return row.tenant if row else None


class TenantContextMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        tenant=None
        if getattr(request,"user",None) and request.user.is_authenticated:
            tenant=getattr(request.user,"tenant",None)
        if tenant is None:
            tenant=_tenant_from_host(request)
        token=_current_tenant.set(tenant)
        request.tenant=tenant
        try:
            return self.get_response(request)
        finally:
            _current_tenant.reset(token)
