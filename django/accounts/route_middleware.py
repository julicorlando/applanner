from django.core.exceptions import PermissionDenied

from .permissions import has_capability


PREFIX_CAPABILITIES={
    "/app/agenda/":"agenda.manage",
    "/app/financeiro/":"finance.manage",
    "/app/barbearia/":"barber.manage",
    "/app/arena/":"arena.manage",
    "/app/auto/":"auto.manage",
    "/app/relacionamento/":"engagement.manage",
    "/app/saude/":"healthcare.manage",
    "/app/suporte/":"support.manage",
}


class CapabilityRouteMiddleware:
    """
    Enforces RBAC after a user has explicit UserRole links.
    Legacy users without UserRole keep their pre-migration access until classified.
    """
    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        user=getattr(request,"user",None)
        if user and user.is_authenticated and not user.is_superuser and user.role_links.exists():
            path=request.path
            required=None
            for prefix,capability in PREFIX_CAPABILITIES.items():
                if path.startswith(prefix):
                    required=capability
                    break
            if required is None and path.startswith("/app/"):
                parts=[p for p in path.split("/") if p]
                if len(parts)>=2:
                    required={
                        "agenda":"agenda.manage","financeiro":"finance.manage",
                        "barbearia":"barber.manage","arena":"arena.manage","auto":"auto.manage",
                        "relacionamento":"engagement.manage","saude":"healthcare.manage",
                        "suporte":"support.manage",
                    }.get(parts[1])
            if required and not has_capability(user,required):
                raise PermissionDenied(f"Permissão necessária: {required}")
        return self.get_response(request)
