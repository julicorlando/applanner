from accounts.permissions import require_any_capability
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404,redirect,render

from tenants.models import Tenant
from .models import SupportMessage,SupportTicket


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
    tenant=_tenant(request)
    ticket=get_object_or_404(
        SupportTicket.objects.select_related("assigned_to","user").prefetch_related("messages__user"),
        pk=pk,tenant=tenant,
    )
    form=MessageForm(request.POST or None,request.FILES or None)
    if request.method=="POST":
        action=request.POST.get("action")
        if action=="message" and form.is_valid():
            row=form.save(commit=False);row.ticket=ticket;row.user=request.user;row.save()
            if request.user==ticket.user:
                ticket.status=SupportTicket.Status.OPEN
            elif request.user.is_staff or request.user.is_superuser:
                ticket.status=SupportTicket.Status.WAITING_USER
            ticket.save(update_fields=["status","updated_at"])
            messages.success(request,"Mensagem enviada.")
        elif action=="status" and (request.user.is_staff or request.user.is_superuser):
            value=request.POST.get("status")
            if value in {v for v,_ in SupportTicket.Status.choices}:
                ticket.status=value;ticket.save(update_fields=["status","updated_at"])
                messages.success(request,"Status atualizado.")
        return redirect("support-ticket-detail",pk=ticket.pk)
    return render(request,"operations/ticket_detail.html",{
        "ticket":ticket,"form":form,"status_choices":SupportTicket.Status.choices,
    })
