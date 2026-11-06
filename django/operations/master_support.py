"""Platform support management; internal notes never enter the customer thread."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from accounts.models import User
from core.audit import append_audit
from .models import SupportTicket,SupportMessage,SupportAccessSession

class TicketManagementForm(forms.ModelForm):
    class Meta:
        model=SupportTicket
        fields=['assigned_to','due_at','status','solution']
        labels={'assigned_to':'Responsável','due_at':'Prazo de atendimento','status':'Situação','solution':'Solução aplicada (visível à empresa)'}
        widgets={'due_at':forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'),'solution':forms.Textarea(attrs={'rows':4})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['assigned_to'].queryset=User.objects.filter(is_active=True,is_staff=True,tenant__isnull=True,deleted_at__isnull=True).filter(Q(is_superuser=True)|Q(role__in=['master-support','support']))
    def clean(self):
        data=super().clean()
        if data.get('status') in {'resolved','closed'} and not (data.get('solution') or '').strip():
            self.add_error('solution','Descreva a solução antes de resolver ou fechar o chamado.')
        return data

class InternalNoteForm(forms.Form):
    message=forms.CharField(label='Anotação interna',max_length=5000,widget=forms.Textarea(attrs={'rows':3}))

@login_required
def ticket_detail(request,pk):
    user=request.user
    if not user.is_superuser and not (user.is_active and user.is_staff and not user.tenant_id and user.role=='master-support'): raise PermissionDenied
    ticket=get_object_or_404(SupportTicket.objects.select_related('tenant','assigned_to','user'),pk=pk)
    form=TicketManagementForm(instance=ticket);note=InternalNoteForm()
    if request.method=='POST':
        with transaction.atomic():
            ticket=SupportTicket.objects.select_for_update().get(pk=pk)
            if request.POST.get('action')=='note':
                note=InternalNoteForm(request.POST)
                if note.is_valid():
                    row=SupportMessage.objects.create(ticket=ticket,user=user,message=note.cleaned_data['message'],is_internal=True)
                    append_audit(request=request,user=user,tenant=ticket.tenant,action='SUPPORT_INTERNAL_NOTE',entity_type='SupportTicket',entity_id=pk,after={'note_id':row.pk})
                    messages.success(request,'Anotação interna registrada.');return redirect('master-support-ticket',pk=pk)
            elif request.POST.get('action')=='manage':
                before={'status':ticket.status,'assigned_to_id':ticket.assigned_to_id,'due_at':str(ticket.due_at),'solution':ticket.solution}
                form=TicketManagementForm(request.POST,instance=ticket)
                if form.is_valid():
                    row=form.save(commit=False)
                    row.resolved_at=(row.resolved_at or timezone.now()) if row.status in {'resolved','closed'} else None
                    row.save(update_fields=['assigned_to','due_at','status','solution','resolved_at','updated_at'])
                    if row.status in {'resolved','closed'}: SupportAccessSession.objects.filter(ticket=row,ended_at__isnull=True).update(ended_at=timezone.now())
                    append_audit(request=request,user=user,tenant=row.tenant,action='SUPPORT_TICKET_MANAGED',entity_type='SupportTicket',entity_id=pk,before=before,after={'status':row.status,'assigned_to_id':row.assigned_to_id,'due_at':str(row.due_at)})
                    messages.success(request,'Chamado atualizado.');return redirect('master-support-ticket',pk=pk)
    return render(request,'master/support_ticket.html',{'ticket':ticket,'form':form,'note_form':note,'thread':ticket.messages.select_related('user').order_by('created_at'),'overdue':bool(ticket.due_at and ticket.due_at<timezone.now() and ticket.status not in {'resolved','closed'})})
