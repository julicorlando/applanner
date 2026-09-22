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
from accounts.models import User
from .models import CommercialCommission, CommercialProfile, Lead, Proposal
from .services import approve_proposal, change_lead_status, claim_lead, transfer_lead


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
    commissions=CommercialCommission.objects.select_related("commercial_user","tenant").order_by("-created_at")
    count_qs=Lead.objects.all()
    if not request.user.is_superuser:
        leads=(leads.filter(assigned_to=request.user) | Lead.objects.filter(assigned_to__isnull=True)).distinct()
        proposals=proposals.filter(commercial_user=request.user)
        commissions=commissions.filter(commercial_user=request.user)
        count_qs=Lead.objects.filter(assigned_to=request.user)
    return render(request,"commercial/dashboard.html",{
        "profile":profile,
        "lead_counts":dict(count_qs.values_list("status").annotate(total=Count("id"))),
        "leads":leads[:100],
        "proposals":proposals[:60],
        "commissions":commissions[:60],
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
            elif action=="transfer":
                target=get_object_or_404(
                    User,pk=request.POST.get("to_user"),
                    commercial_profile__active=True,is_active=True,
                )
                transfer_lead(
                    lead=lead,to_user=target,actor=request.user,
                    notes=request.POST.get("notes",""),
                )
                messages.success(request,"Lead transferido.")
            elif action=="update":
                lead.notes=request.POST.get("notes","")[:5000]
                value=(request.POST.get("next_contact_at") or "").strip()
                if value:
                    try:
                        next_contact=timezone.datetime.fromisoformat(value)
                    except ValueError as exc:
                        raise ValidationError("Data do próximo contato inválida.") from exc
                    lead.next_contact_at=timezone.make_aware(next_contact) if timezone.is_naive(next_contact) else next_contact
                else:
                    lead.next_contact_at=None
                lead.save(update_fields=["notes","next_contact_at","updated_at"])
                messages.success(request,"Lead atualizado.")
            else:
                raise ValidationError("Ação comercial inválida.")
        except ValidationError as exc:
            messages.error(request,str(exc))
        return redirect("commercial-lead-detail",pk=lead.pk)
    return render(request,"commercial/lead_detail.html",{
        "lead":lead,
        "history":lead.history.select_related("actor_user","from_user","to_user").order_by("-created_at"),
        "status_choices":Lead.Status.choices,
        "commercial_users":User.objects.filter(
            commercial_profile__active=True,is_active=True
        ).order_by("email"),
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
        proposal.base_plan=proposal.plan
        proposal.modules=list(
            proposal.plan.module_links.filter(enabled=True,module__active=True)
            .select_related("module").values_list("module__name",flat=True)
        )
        proposal.features=dict(proposal.plan.features or {})
        proposal.save()
        messages.success(request,"Proposta criada.")
        return redirect("commercial-proposal-detail",pk=proposal.pk)
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
    return redirect("commercial-proposal-detail",pk=proposal.pk)


@login_required
def proposal_detail(request,pk):
    _require_commercial(request.user)
    proposal=get_object_or_404(
        Proposal.objects.select_related("plan","commercial_user","approved_by"),pk=pk
    )
    if not request.user.is_superuser and proposal.commercial_user_id!=request.user.id:
        raise PermissionDenied
    public_url=request.build_absolute_uri(
        redirect("commercial-public-proposal",token=proposal.public_token).url
    )
    return render(request,"commercial/proposal_detail.html",{
        "proposal":proposal,"public_url":public_url,
    })


@login_required
def commission_action(request,pk):
    _require_commercial(request.user)
    if not request.user.is_superuser or request.method!="POST":
        raise PermissionDenied
    row=get_object_or_404(CommercialCommission,pk=pk)
    action=request.POST.get("action")
    now=timezone.now()
    if action=="approve":
        row.status=CommercialCommission.Status.APPROVED
        row.approved_at=now
        row.save(update_fields=["status","approved_at","updated_at"])
        messages.success(request,"Comissão aprovada.")
    elif action=="pay":
        row.status=CommercialCommission.Status.PAID
        row.paid_at=now
        row.save(update_fields=["status","paid_at","updated_at"])
        messages.success(request,"Comissão marcada como paga.")
    elif action=="reverse":
        row.status=CommercialCommission.Status.REVERSED
        row.reversed_at=now
        row.save(update_fields=["status","reversed_at","updated_at"])
        messages.success(request,"Comissão estornada.")
    else:
        messages.error(request,"Ação inválida.")
    return redirect("commercial-dashboard")


def public_proposal(request,token):
    proposal=get_object_or_404(Proposal.objects.select_related("plan"),public_token=token)
    if proposal.expires_at and proposal.expires_at<=timezone.now() and proposal.status!=Proposal.Status.CONVERTED:
        proposal.status=Proposal.Status.EXPIRED
        proposal.save(update_fields=["status","updated_at"])
    if proposal.status==Proposal.Status.SENT:
        proposal.status=Proposal.Status.VIEWED
        proposal.save(update_fields=["status","updated_at"])
    error=""
    if request.method=="POST":
        try:
            from .services import accept_proposal
            accept_proposal(
                proposal=proposal,
                ip=request.META.get("REMOTE_ADDR") or "",
                user_agent=request.META.get("HTTP_USER_AGENT") or "",
            )
            messages.success(request,"Proposta aceita com sucesso.")
            return redirect("commercial-public-proposal",token=token)
        except ValidationError as exc:
            error=str(exc)
    return render(request,"commercial/public_proposal.html",{"proposal":proposal,"error":error})
