from contextvars import ContextVar

_current_tenant=ContextVar("current_tenant",default=None)


def get_current_tenant():
    return _current_tenant.get()


class TenantContextMiddleware:
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        tenant=None
        if getattr(request,"user",None) and request.user.is_authenticated:
            tenant=getattr(request.user,"tenant",None)
        token=_current_tenant.set(tenant)
        request.tenant=tenant
        try:
            return self.get_response(request)
        finally:
            _current_tenant.reset(token)
