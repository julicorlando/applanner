import re
from django.core.exceptions import PermissionDenied

from .permissions import has_capability




RECEPTION_MUTATION_PREFIXES=(
    "/app/hoje/",
    "/app/cliente/",
    "/app/agenda/",
    "/app/financeiro/pdv/",
    "/app/barbearia/fila/",
    "/app/arena/espera-arena/",
    "/app/relacionamento/inteligencia/",
    "/app/relacionamento/espera/",
    "/app/recepcao/agendamento/",
)


CLINIC_OPERATION_PATHS = {
    "/app/clinica/operacao/snapshot/", "/app/clinica/operacao/sincronizar/",
    "/app/clinica/tv/", "/app/clinica/tv/chamar/",
}


def _reception_mutation_allowed(path):
    if path in {"/app/clinica/operacao/sincronizar/", "/app/clinica/tv/chamar/"}:
        return True  # Views still enforce module, tenant and clinical/financial permissions per operation.
    return bool(re.fullmatch(r"/app/barbearia/comandas/[0-9]+/vale/",path)) or any(path.startswith(prefix) for prefix in RECEPTION_MUTATION_PREFIXES)


PREFIX_CAPABILITIES={
    "/app/agenda/":"agenda.manage",
    "/app/financeiro/":"finance.manage",
    "/app/barbearia/":"barber.manage",
    "/app/arena/":"arena.manage",
    "/app/auto/":"auto.manage",
    "/app/relacionamento/":"engagement.manage",
    "/app/saude/":"healthcare.manage",
    "/app/odontologia/":"healthcare.manage",
    "/app/clinica/":"healthcare.manage",
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
        if user and user.is_authenticated and user.role=="professional" and not user.is_superuser:
            own_calendar_read = request.method in {'GET', 'HEAD'} and request.path in {'/app/calendario/', '/app/identidade/logo/'}
            from healthcare.navigation import workspace_enabled
            own_physio_read=(request.method in {'GET','HEAD'} and request.path in {'/app/','/app/fisioterapia/dashboard/','/app/fisioterapia/configuracoes/','/app/odontologia/dashboard/','/app/odontologia/configuracoes/'} and workspace_enabled(request))
            if request.path.startswith("/app/") and not request.path.startswith("/app/profissional/") and not own_physio_read and not own_calendar_read and not request.path.startswith(("/app/saude/", "/app/odontologia/", "/app/clinica/")):
                raise PermissionDenied("A conta profissional acessa apenas sua própria área.")
        if (
            user and user.is_authenticated and not user.is_superuser
            and user.role=="reception" and request.method not in {"GET","HEAD","OPTIONS"}
            and request.path.startswith("/app/")
            and not _reception_mutation_allowed(request.path)
        ):
            raise PermissionDenied(
                "A recepção possui acesso de consulta nesta área, sem permissão para alterar."
            )
        if user and user.is_authenticated and not user.is_superuser and user.role_links.exists():
            path=request.path
            required="agenda.manage" if path in CLINIC_OPERATION_PATHS else None
            for prefix,capability in (() if required else PREFIX_CAPABILITIES.items()):
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
