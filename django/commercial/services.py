import hashlib
import secrets
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    CommercialCommission, CommercialProfile, Lead, LeadHistory, LeadPrivacyEvent,
    Proposal, ProposalAcceptance,
)


@transaction.atomic
def claim_lead(*,lead,user):
    lead=Lead.objects.select_for_update().get(pk=lead.pk)
    if lead.do_not_contact:
        raise ValidationError("Lead marcado como não contatar.")
    if lead.assigned_to_id and lead.assigned_to_id!=user.id:
        raise ValidationError("Lead já está em atendimento.")
    old=lead.assigned_to
    lead.assigned_to=user
    lead.assigned_at=timezone.now()
    lead.status=Lead.Status.IN_SERVICE
    lead.save(update_fields=["assigned_to","assigned_at","status","updated_at"])
    LeadHistory.objects.create(
        lead=lead,from_user=old,to_user=user,action=LeadHistory.Action.CLAIMED,actor_user=user
    )
    return lead


@transaction.atomic
def transfer_lead(*,lead,to_user,actor,notes=""):
    lead=Lead.objects.select_for_update().get(pk=lead.pk)
    old=lead.assigned_to
    lead.assigned_to=to_user
    lead.assigned_at=timezone.now()
    lead.last_transferred_by=actor
    lead.last_transferred_at=timezone.now()
    lead.save(update_fields=[
        "assigned_to","assigned_at","last_transferred_by","last_transferred_at","updated_at"
    ])
    LeadHistory.objects.create(
        lead=lead,from_user=old,to_user=to_user,action=LeadHistory.Action.TRANSFERRED,
        actor_user=actor,notes=notes[:500],
    )
    return lead


@transaction.atomic
def change_lead_status(*,lead,status,actor,loss_reason=""):
    valid={v for v,_ in Lead.Status.choices}
    if status not in valid:
        raise ValidationError("Status comercial inválido.")
    lead=Lead.objects.select_for_update().get(pk=lead.pk)
    old=lead.status
    lead.status=status
    if status==Lead.Status.LOST:
        lead.loss_reason=loss_reason[:255]
    lead.save(update_fields=["status","loss_reason","updated_at"])
    LeadHistory.objects.create(
        lead=lead,from_user=lead.assigned_to,to_user=lead.assigned_to,
        action=LeadHistory.Action.STATUS_CHANGED,actor_user=actor,
        notes=f"{old} -> {status}",
    )
    return lead


def proposal_snapshot(proposal):
    return {
        "id":proposal.pk,
        "title":proposal.title,
        "customer_name":proposal.customer_name,
        "customer_email":proposal.customer_email,
        "plan_id":proposal.plan_id,
        "base_plan_id":proposal.base_plan_id,
        "discount_percent":str(proposal.discount_percent),
        "final_price":str(proposal.final_price),
        "modules":proposal.modules,
        "features":proposal.features,
        "expires_at":proposal.expires_at.isoformat() if proposal.expires_at else None,
    }


@transaction.atomic
def approve_proposal(*,proposal,user,approved=True):
    proposal=Proposal.objects.select_for_update().get(pk=proposal.pk)
    proposal.approval_status=Proposal.Approval.APPROVED if approved else Proposal.Approval.REJECTED
    proposal.approved_by=user
    proposal.approved_at=timezone.now()
    proposal.save(update_fields=["approval_status","approved_by","approved_at","updated_at"])
    return proposal


@transaction.atomic
def accept_proposal(*,proposal,ip="",user_agent=""):
    proposal=Proposal.objects.select_for_update().select_related("plan").get(pk=proposal.pk)
    if proposal.expires_at and proposal.expires_at<=timezone.now():
        proposal.status=Proposal.Status.EXPIRED
        proposal.save(update_fields=["status","updated_at"])
        raise ValidationError("Proposta expirada.")
    if proposal.approval_status==Proposal.Approval.PENDING:
        raise ValidationError("Proposta aguarda aprovação.")
    if proposal.approval_status==Proposal.Approval.REJECTED:
        raise ValidationError("Proposta rejeitada.")

    snapshot=proposal_snapshot(proposal)
    digest=ProposalAcceptance.hash_snapshot(snapshot)
    ip_hash=hashlib.sha256(ip.encode()).hexdigest() if ip else ""
    acceptance,_=ProposalAcceptance.objects.get_or_create(
        proposal=proposal,
        defaults={
            "document_hash":digest,
            "proposal_snapshot":snapshot,
            "ip_hash":ip_hash,
            "user_agent":user_agent[:500],
            "accepted_at":timezone.now(),
        },
    )
    proposal.accepted_at=acceptance.accepted_at
    proposal.accepted_ip_hash=ip_hash
    proposal.status=Proposal.Status.CONVERTED
    proposal.save(update_fields=["accepted_at","accepted_ip_hash","status","updated_at"])
    return acceptance


@transaction.atomic
def project_commission(*,commercial_user,tenant,payment=None,base_amount=None):
    profile=CommercialProfile.objects.filter(user=commercial_user,active=True).first()
    if not profile:
        raise ValidationError("Perfil comercial inativo.")
    amount=Decimal(str(base_amount if base_amount is not None else (payment.amount if payment else 0)))
    commission=(amount*profile.commission_percent/Decimal("100")).quantize(Decimal("0.01"))
    row,_=CommercialCommission.objects.update_or_create(
        commercial_user=commercial_user,tenant=tenant,
        defaults={
            "payment":payment,"base_amount":amount,
            "commission_percent":profile.commission_percent,
            "commission_amount":commission,
            "status":CommercialCommission.Status.PROJECTED,
        },
    )
    return row


@transaction.atomic
def anonymize_lead(*,lead,actor=None):
    lead=Lead.objects.select_for_update().get(pk=lead.pk)
    marker=f"anon-{lead.pk}-{secrets.token_hex(4)}"
    lead.name="Lead anonimizado"
    lead.phone=""
    lead.email=f"{marker}@invalid.local"
    lead.notes=""
    lead.loss_reason=""
    lead.ip_hash=""
    lead.consent_user_agent=""
    lead.anonymized_at=timezone.now()
    lead.do_not_contact=True
    lead.save()
    LeadPrivacyEvent.objects.create(
        lead=lead,action=LeadPrivacyEvent.Action.ANONYMIZED,actor_user=actor
    )
    return lead
