"""Least-privilege platform roles. Unknown Master routes are denied by default."""
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.http import Http404

PLATFORM_ROLES = {
    'master-finance': ('Financeiro da plataforma', 'master-finance-dashboard'),
    'master-support': ('Suporte da plataforma', 'master-alerts'),
    'master-commercial': ('Comercial da plataforma', 'master-retention'),
}
READ_ROUTES = {
    'master-finance': {'master-finance-dashboard','master-charges','master-charge-detail','master-reports'},
    'master-support': {'master-alerts','master-company-health','master-support-ticket','master-runtime-monitor'},
    'master-commercial': {'master-retention','master-company-health'},
}
RESOURCES = {'master-finance': {'despesas','financeiro'}, 'master-support': {'suporte','incidentes'}, 'master-commercial': set()}

class MasterAccessMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request): return self.get_response(request)
    def process_view(self,request,view,args,kwargs):
        user=request.user
        if not user.is_authenticated or user.is_superuser or user.role not in PLATFORM_ROLES:
            return None
        if user.tenant_id or not user.is_staff:
            raise PermissionDenied('A conta da plataforma deve ser interna e sem empresa vinculada.')
        name=getattr(request.resolver_match,'url_name','')
        # Never let platform operators fall through tenant, API or Django admin routes.
        if request.path.startswith(('/app/','/api/','/admin/')):
            raise PermissionDenied('Este perfil não permite acessar esta área.')
        if not request.path.startswith('/master/'):
            return None
        if name=='master-home': return redirect(PLATFORM_ROLES[user.role][1])
        if name in READ_ROUTES[user.role] and request.method in {'GET','HEAD','OPTIONS'}:
            return None
        if user.role=='master-finance' and name in {'master-charge-consult','master-financial-consult'}: return None
        if user.role=='master-commercial' and name=='master-retention-note': return None
        if user.role=='master-support' and name=='master-support-ticket': return None
        if name in {'master-resource-list','master-resource-create','master-resource-edit'} and kwargs.get('slug') in RESOURCES[user.role]:
            return None
        raise PermissionDenied('Ação restrita à administração da plataforma.')


class MasterAdminGateMiddleware:
    """Hide every Django admin endpoint unless the current session is a Master."""
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        path=request.path_info
        if path=='/admin' or path.startswith('/admin/'):
            user=request.user
            if not (user.is_authenticated and user.is_active and user.is_superuser and user.is_staff):
                raise Http404
        return self.get_response(request)
