from django.contrib.auth import login,logout
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone

from accounts.models import User
from accounts.permissions import has_capability
from core.models import AuditLog
from .models import SupportAccessSession,SupportTicket


class SupportImpersonationMiddleware:
    """Revalidate the customer's consent on every request, including after revocation."""

    def __init__(self,get_response):
        self.get_response=get_response

    def __call__(self,request):
        access_id=request.session.get("support_access_id")
        if not access_id:
            return self.get_response(request)

        actor_id=request.session.get("support_actor_id")
        actor=User.objects.filter(pk=actor_id,is_active=True,tenant__isnull=True).first()
        access=SupportAccessSession.objects.select_related("ticket").filter(
            pk=access_id,master_user_id=actor_id,ended_at__isnull=True,
        ).first()
        valid=(
            actor is not None and access is not None and
            has_capability(actor,"master.support.impersonate") and
            request.user.is_authenticated and
            request.user.pk==access.impersonated_user_id and
            request.user.is_active and request.user.tenant_id==access.tenant_id and
            access.ticket.remote_access_allowed and
            access.ticket.status not in {SupportTicket.Status.RESOLVED,SupportTicket.Status.CLOSED}
        )
        if not valid:
            if access:
                SupportAccessSession.objects.filter(pk=access.pk,ended_at__isnull=True).update(ended_at=timezone.now())
            if actor:
                login(request,actor,backend="django.contrib.auth.backends.ModelBackend")
                request.session["session_version"]=actor.session_version
            else:
                logout(request)
            request.session.pop("support_actor_id",None)
            request.session.pop("support_access_id",None)
            return redirect("portal-home")

        request.support_actor=actor
        request.support_access=access
        if request.path.startswith(("/admin/","/master/","/account/")) and request.path!="/account/logout/":
            return HttpResponseForbidden("Área de segurança indisponível durante acesso assistido.")
        response=self.get_response(request)
        if request.method in {"POST","PUT","PATCH","DELETE"}:
            AuditLog.objects.create(
                tenant_id=access.tenant_id,user=actor,
                action="SUPPORT_ASSISTED_ACTION",entity_type="support_tickets",
                entity_id=access.ticket_id,ip_address=request.META.get("REMOTE_ADDR") or None,
                after={"path":request.path[:500],"method":request.method,"status":response.status_code},
            )
        if request.session.get("support_access_id")!=access.pk:
            SupportAccessSession.objects.filter(pk=access.pk,ended_at__isnull=True).update(ended_at=timezone.now())
        return response
