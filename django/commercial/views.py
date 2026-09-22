import secrets
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from billing.models import Plan
from .models import CommercialProfile, Lead, Proposal
from .services import approve_proposal, change_lead_status, claim_lead


def _require_commercial(user):
    if user.is_superuser:
        return None
    profile=CommercialProfile.objects.filter(user=user,active=True).first()
    if not profile:
        raise PermissionDenied("Acesso restrito ao time comercial.")
    return profile


class ProposalForm(forms.ModelForm):
    class Meta:
        model=Proposal
        fields=["plan","title","customer_name","customer_email","discount_percent","final_price","notes","expires_at"]
        widgets={
            "expires_at":forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M"),
            "notes":forms.Textarea(attrs={"rows":4}),
        }

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields["plan"].queryset=Plan.objects.filter(active=True).order_by("sort_order","name")
        self.fields["expires_at"].input_formats=["%Y-%m-%dT%H:%M"]


@login_required
def dashboard(request):
    profile=_require_commercial(request.user)
    leads=Lead.objects.select_related("assigned_to").order_by("-created_at")
    proposals=Proposal.objects.select_related("plan","commercial_user").order_by("-created_at")
    if not request.user.is_superuser:
        leads=leads.filter(assigned_to=request.user) | Lead.objects.filter(assigned_to__isnull=True)
        proposals=proposals.filter(commercial_user=request.user)
    return render(request,"commercial/dashboard.html",{
        "profile":profile,
        "lead_counts":dict(Lead.objects.values_list("status").annotate(total=Count("id"))),
        "leads":leads[:100],
        "proposals":proposals[:60],
    })


@login_required
def lead_detail(request,pk):
    _require_commercial(request.user)
    lead=get_object_or_404(Lead.objects.select_related("assigned_to"),pk=pk)
    if not request.user.is_superuser and lead.assigned_to_id not in {None,request.user.id}:
        raise PermissionDenied
    if request.method=="POST":
        action=request.POST.get("action")
        try:
            if action=="claim":
                claim_lead(lead=lead,user=request.user)
                messages.success(request,"Lead assumido.")
            elif action=="status":
                change_lead_status(
                    lead=lead,status=request.POST.get("status",""),actor=request.user,
                    loss_reason=request.POST.get("loss_reason",""),
                )
                messages.success(request,"Status atualizado.")
            else:
                raise ValidationError("Ação comercial inválida.")
        except ValidationError as exc:
            messages.error(request,str(exc))
        return redirect("commercial-lead-detail",pk=lead.pk)
    return render(request,"commercial/lead_detail.html",{
        "lead":lead,
        "history":lead.history.select_related("actor_user","from_user","to_user").order_by("-created_at"),
        "status_choices":Lead.Status.choices,
    })


@login_required
def proposal_create(request):
    profile=_require_commercial(request.user)
    form=ProposalForm(request.POST or None)
    if request.method=="POST" and form.is_valid():
        proposal=form.save(commit=False)
        proposal.commercial_user=request.user
        proposal.public_token=secrets.token_hex(16)
        discount=Decimal(str(proposal.discount_percent or 0))
        max_discount=profile.max_discount_percent if profile else Decimal("100")
        proposal.approval_status=(
            Proposal.Approval.PENDING if discount>max_discount else Proposal.Approval.NOT_REQUIRED
        )
        proposal.save()
        messages.success(request,"Proposta criada.")
        return redirect("commercial-dashboard")
    return render(request,"commercial/proposal_form.html",{"form":form})


@login_required
def proposal_action(request,pk):
    _require_commercial(request.user)
    proposal=get_object_or_404(Proposal,pk=pk)
    if not request.user.is_superuser and proposal.commercial_user_id!=request.user.id:
        raise PermissionDenied
    if request.method!="POST":
        raise PermissionDenied
    action=request.POST.get("action")
    if action in {"approve","reject"}:
        if not request.user.is_superuser:
            raise PermissionDenied
        approve_proposal(proposal=proposal,user=request.user,approved=action=="approve")
        messages.success(request,"Aprovação da proposta atualizada.")
    elif action=="send":
        proposal.status=Proposal.Status.SENT
        proposal.save(update_fields=["status","updated_at"])
        messages.success(request,"Proposta marcada como enviada.")
    else:
        messages.error(request,"Ação inválida.")
    return redirect("commercial-dashboard")
