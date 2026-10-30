"""Explicit self-identification for the clinic's existing scheduling profile."""
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from billing.entitlements import require_module
from core.audit import append_audit
from scheduling.models import Professional
from tenants.models import Tenant
from .models import ClinicalRegistration
from .navigation import dental_workspace, is_physiotherapy


def eligible_profiles(user):
    return Professional.objects.filter(tenant_id=user.tenant_id, active=True).filter(
        Q(user__isnull=True) | Q(user=user)
    ).order_by("pk")


def clinical_destination(tenant):
    if dental_workspace(tenant):
        return "dental-assessments"
    if is_physiotherapy(tenant):
        return "physio-assessments"
    return None


class ClinicalActivationForm(forms.Form):
    professional = forms.ModelChoiceField(queryset=Professional.objects.none(), label="Perfil de agendamento incluído")
    professional_name = forms.CharField(max_length=190, label="Seu nome completo como profissional de saúde")
    council = forms.ChoiceField(choices=ClinicalRegistration._meta.get_field("council").choices, label="Conselho profissional")
    number = forms.CharField(max_length=40, label="Número do registro profissional")
    jurisdiction = forms.CharField(max_length=4, label="UF do CRO ou região numérica do CREFITO")
    specialties = forms.CharField(max_length=300, required=False, label="Especialidades")
    attestation = forms.BooleanField(label="Sou o profissional de saúde informado e confirmo o vínculo desta conta ao perfil selecionado para realizar atendimentos clínicos.")

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["professional"].queryset = eligible_profiles(user)
        if dental_workspace(user.tenant):
            self.fields["council"].choices = [("CRO", "CRO")]
            self.fields["council"].initial = "CRO"
        elif is_physiotherapy(user.tenant):
            self.fields["council"].choices = [("CREFITO", "CREFITO")]
            self.fields["council"].initial = "CREFITO"
        if not self.is_bound:
            profile = eligible_profiles(user).filter(user=user).first() or eligible_profiles(user).first()
            if profile:
                self.initial["professional"] = profile.pk
                registration = ClinicalRegistration.objects.filter(professional=profile).first()
                if registration:
                    for field in ("professional_name", "council", "number", "jurisdiction", "specialties"):
                        self.initial[field] = getattr(registration, field)
            self.initial.setdefault("professional_name", user.get_full_name())

    def clean_professional_name(self):
        name = self.cleaned_data["professional_name"].strip()
        if (name.casefold() == self.user.tenant.name.strip().casefold()
                and name.casefold() != self.user.get_full_name().strip().casefold()):
            raise ValidationError("Informe o nome da pessoa responsável; o nome comercial da clínica será preservado no agendamento.")
        return name

    def clean(self):
        data = super().clean()
        required = ("professional", "professional_name", "council", "number", "jurisdiction")
        if all(key in data for key in required):
            registration = ClinicalRegistration(**{key: data[key] for key in required}, specialties=data.get("specialties", ""))
            registration.full_clean(exclude=["professional"], validate_unique=False, validate_constraints=False)
            data["jurisdiction"] = registration.jurisdiction
        return data


@transaction.atomic
def activate_clinician(*, user, form, request=None):
    if not user.is_authenticated or not user.tenant_id or form.user.pk != user.pk:
        raise PermissionDenied
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    actor = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not actor.is_active or actor.tenant_id != user.tenant_id or actor.is_superuser or actor.role not in {"owner", "tenant-admin"}:
        raise PermissionDenied("Somente o responsável da clínica pode configurar seu próprio vínculo clínico.")
    require_module(actor.tenant, "medical_records")
    if not form.is_valid():
        raise ValidationError("Revise a identificação profissional e confirme o vínculo.")
    profile = Professional.objects.select_for_update().get(pk=form.cleaned_data["professional"].pk)
    if profile.tenant_id != actor.tenant_id or not profile.active or profile.user_id not in {None, actor.pk}:
        raise ValidationError("O perfil foi alterado por outra sessão. Atualize a página e selecione um perfil disponível.")
    values = {key: form.cleaned_data[key] for key in ("professional_name", "council", "number", "jurisdiction", "specialties")}
    registration = ClinicalRegistration.objects.filter(professional=profile).first()
    changed = profile.user_id != actor.pk or registration is None or any(getattr(registration, key) != value for key, value in values.items())
    if profile.user_id != actor.pk:
        profile.user = actor
        profile.save(update_fields=["user", "updated_at"])
    ClinicalRegistration.objects.update_or_create(professional=profile, defaults=values)
    if changed:
        append_audit(tenant=actor.tenant, user=actor, request=request,
                     action="clinical.profile.self_activated", entity_type="Professional", entity_id=profile.pk,
                     after={"user_id": actor.pk, "council": values["council"], "self_attested": True})
    return profile
