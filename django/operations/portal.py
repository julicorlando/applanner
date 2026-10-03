from accounts.models import User
from accounts.permissions import has_capability,require_any_capability
from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone

from tenants.models import Tenant
from core.models import AuditLog
from .models import SupportAccessSession,SupportMessage,SupportTicket


def _tenant(request):
    if request.user.tenant_id:return request.user.tenant
    if request.user.is_superuser:
        tid=request.session.get("portal_tenant_id")
        if tid:return Tenant.objects.filter(pk=tid).first()
    raise PermissionDenied("Selecione uma empresa.")


class MessageForm(forms.ModelForm):
    class Meta:
        model=SupportMessage
        fields=["message","attachment"]
        widgets={"message":forms.Textarea(attrs={"rows":4})}


@login_required
def ticket_detail(request,pk):
    require_any_capability(request.user,"support.manage")
    tickets=SupportTicket.objects.select_related("assigned_to","user").prefetch_related("messages__user")
    if request.user.tenant_id:
        tickets=tickets.filter(tenant=request.user.tenant)
    elif not (request.user.is_active and has_capability(request.user,"support.manage")):
        raise PermissionDenied
    elif request.user.role=="commercial":
        tickets=tickets.filter(assigned_to=request.user)
    ticket=get_object_or_404(tickets,pk=pk)
    form=MessageForm(request.POST or None,request.FILES or None)
    if request.method=="POST":
        action=request.POST.get("action")
        if action=="remote_access":
            if request.user.pk!=ticket.user_id:
                raise PermissionDenied("Somente o solicitante pode autorizar o acesso.")
            with transaction.atomic():
                ticket=SupportTicket.objects.select_for_update().get(pk=ticket.pk)
                allowed=request.POST.get("allowed")=="1"
                if allowed and ticket.status==SupportTicket.Status.CLOSED:
                    raise PermissionDenied("Chamado encerrado.")
                ticket.remote_access_allowed=allowed
                ticket.remote_access_allowed_at=timezone.now() if allowed else None
                ticket.remote_access_revoked_at=None if allowed else timezone.now()
                ticket.save(update_fields=[
                    "remote_access_allowed","remote_access_allowed_at",
                    "remote_access_revoked_at","updated_at",
                ])
                if not allowed:
                    SupportAccessSession.objects.filter(ticket=ticket,ended_at__isnull=True).update(ended_at=timezone.now())
            messages.success(request,"Autorização de suporte atualizada.")
        elif action=="message" and form.is_valid():
            row=form.save(commit=False);row.ticket=ticket;row.user=request.user;row.save()
            if request.user==ticket.user:
                ticket.status=SupportTicket.Status.OPEN
            elif request.user.is_staff or request.user.is_superuser:
                ticket.status=SupportTicket.Status.WAITING_USER
            ticket.save(update_fields=["status","updated_at"])
            messages.success(request,"Mensagem enviada.")
        elif action=="status" and request.user.tenant_id is None and has_capability(request.user,"support.manage"):
            value=request.POST.get("status")
            if value in {v for v,_ in SupportTicket.Status.choices}:
                ticket.status=value;ticket.save(update_fields=["status","updated_at"])
                if value in {SupportTicket.Status.RESOLVED,SupportTicket.Status.CLOSED}:
                    SupportAccessSession.objects.filter(ticket=ticket,ended_at__isnull=True).update(ended_at=timezone.now())
                messages.success(request,"Status atualizado.")
        return redirect("support-ticket-detail",pk=ticket.pk)
    return render(request,"operations/ticket_detail.html",{
        "ticket":ticket,"form":form,"status_choices":SupportTicket.Status.choices,
        "can_impersonate":request.user.tenant_id is None and has_capability(request.user,"master.support.impersonate"),
        "can_manage_status":request.user.tenant_id is None and has_capability(request.user,"support.manage"),
    })


@login_required
@require_POST
def start_access(request,pk):
    actor=request.user
    if actor.tenant_id is not None or not actor.is_active:
        raise PermissionDenied("Acesso assistido restrito à equipe da plataforma.")
    require_any_capability(actor,"master.support.impersonate")
    if request.session.get("support_access_id"):
        raise PermissionDenied("Encerre o acesso assistido atual primeiro.")
    with transaction.atomic():
        ticket=get_object_or_404(SupportTicket.objects.select_for_update(),pk=pk)
        if actor.role=="commercial" and ticket.assigned_to_id!=actor.pk:
            raise PermissionDenied("Chamado não atribuído ao atendente.")
        if not ticket.remote_access_allowed or ticket.status in {
            SupportTicket.Status.RESOLVED,SupportTicket.Status.CLOSED,
        }:
            raise PermissionDenied("Chamado sem autorização ativa do cliente.")
        target=User.objects.filter(tenant_id=ticket.tenant_id,is_active=True).filter(
            Q(role="owner")|Q(role_links__role__slug="owner")
        ).order_by("pk").distinct().first()
        if target is None or target.must_change_password:
            raise PermissionDenied("Proprietário ativo indisponível.")
        access=SupportAccessSession.objects.create(
            ticket=ticket,tenant_id=ticket.tenant_id,master_user=actor,
            impersonated_user=target,started_at=timezone.now(),
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
        AuditLog.objects.create(
            tenant_id=ticket.tenant_id,user=actor,action="SUPPORT_ACCESS_STARTED",
            entity_type="support_tickets",entity_id=ticket.pk,
            ip_address=request.META.get("REMOTE_ADDR") or None,
            after={"access_session_id":access.pk,"impersonated_user_id":target.pk},
        )
    login(request,target,backend="django.contrib.auth.backends.ModelBackend")
    request.session["support_actor_id"]=actor.pk
    request.session["support_access_id"]=access.pk
    request.session["session_version"]=target.session_version
    return redirect("portal-home")


@login_required
@require_POST
def end_access(request):
    access=get_object_or_404(
        SupportAccessSession.objects.select_related("master_user","ticket"),
        pk=request.session.get("support_access_id"),
        impersonated_user=request.user,ended_at__isnull=True,
    )
    if request.session.get("support_actor_id")!=access.master_user_id:
        raise PermissionDenied
    actor=access.master_user
    SupportAccessSession.objects.filter(pk=access.pk,ended_at__isnull=True).update(ended_at=timezone.now())
    AuditLog.objects.create(
        tenant_id=access.tenant_id,user=actor,action="SUPPORT_ACCESS_ENDED",
        entity_type="support_tickets",entity_id=access.ticket_id,
        ip_address=request.META.get("REMOTE_ADDR") or None,
        after={"access_session_id":access.pk},
    )
    login(request,actor,backend="django.contrib.auth.backends.ModelBackend")
    request.session.pop("support_actor_id",None)
    request.session.pop("support_access_id",None)
    request.session["session_version"]=actor.session_version
    return redirect("support-ticket-detail",pk=access.ticket_id)
