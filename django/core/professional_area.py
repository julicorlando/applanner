from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from finance.models import ProfessionalCommission
from scheduling.models import Appointment, Professional


class ProfessionalAccessForm(forms.Form):
    email=forms.EmailField(label="E-mail de acesso")
    password1=forms.CharField(label="Senha temporária",required=False,widget=forms.PasswordInput,
                              help_text="Obrigatória na criação. Ao entrar, o profissional deverá alterá-la.")
    password2=forms.CharField(label="Confirme a senha",required=False,widget=forms.PasswordInput)
    enabled=forms.BooleanField(label="Permitir acesso",required=False,initial=True)

    def __init__(self,*args,professional,**kwargs):
        super().__init__(*args,**kwargs)
        self.professional=professional

    def clean_email(self):
        email=self.cleaned_data["email"].strip().lower()
        user=get_user_model().objects.filter(email__iexact=email).first()
        if user and user.pk!=self.professional.user_id:
            raise ValidationError("Este e-mail já pertence a outra conta.")
        return email

    def clean(self):
        data=super().clean()
        password=data.get("password1") or ""
        if not self.professional.user_id and not password:
            self.add_error("password1","Informe uma senha temporária para criar o acesso.")
        if password!=data.get("password2",""):
            self.add_error("password2","As senhas não coincidem.")
        if password:
            try:
                validate_password(password,self.professional.user)
            except ValidationError as exc:
                self.add_error("password1",exc)
        return data


@login_required
def professional_access(request,pk):
    if not request.user.is_superuser and request.user.role not in {
        "owner","manager","tenant-admin","barber-manager","arena-manager","auto-manager"
    }:
        raise PermissionDenied("Somente a gestão da empresa pode liberar contas profissionais.")
    tenant=request.user.tenant
    if not tenant and request.user.is_superuser:
        from .portal import _require_tenant
        tenant=_require_tenant(request)
    professional=get_object_or_404(Professional.objects.select_related("user"),pk=pk,tenant=tenant)
    initial={"email":professional.user.email if professional.user_id else professional.email,
             "enabled":professional.user.is_active if professional.user_id else True}
    form=ProfessionalAccessForm(request.POST or None,professional=professional,initial=initial)
    if request.method=="POST" and form.is_valid():
        with transaction.atomic():
            # The linked user is optional; avoid an outer join in FOR UPDATE.
            professional=Professional.objects.select_for_update().get(pk=professional.pk)
            data=form.cleaned_data
            if professional.user_id:
                user=professional.user
                if user.tenant_id!=tenant.pk:
                    raise PermissionDenied("Conta vinculada a outra empresa.")
                user.email=data["email"]
                previously_active=user.is_active
                user.is_active=bool(data["enabled"] and professional.active)
                user.role="professional"
                if data["password1"]:
                    user.set_password(data["password1"])
                    user.must_change_password=True
                    user.session_version+=1
                elif previously_active!=user.is_active:
                    user.session_version+=1
                user.role_links.all().delete()
                user.save()
            else:
                user=get_user_model().objects.create_user(
                    email=data["email"],password=data["password1"],tenant=tenant,
                    role="professional",is_active=bool(data["enabled"] and professional.active),
                    must_change_password=True,
                )
                professional.user=user
                professional.save(update_fields=["user"])
            professional.email=data["email"]
            professional.save(update_fields=["email"])
        messages.success(request,"Acesso do profissional atualizado. Compartilhe a senha temporária por um canal seguro.")
        return redirect("portal-resource-list","agenda","profissionais")
    return render(request,"portal/professional_access.html",{
        "form":form,"professional":professional,"tenant":tenant,
    })


@login_required
def professional_area(request):
    if request.user.role!="professional" or not request.user.tenant_id:
        raise PermissionDenied("Área exclusiva do profissional.")
    professional=get_object_or_404(
        Professional,tenant_id=request.user.tenant_id,user=request.user,active=True
    )
    now=timezone.now()
    local_now=timezone.localtime(now)
    month_start=local_now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    appointments=Appointment.objects.filter(tenant=professional.tenant,professional=professional)
    upcoming=appointments.filter(starts_at__gte=now,status__in=[
        Appointment.Status.PENDING,Appointment.Status.CONFIRMED,
    ]).select_related("customer","service").order_by("starts_at")
    month_commissions=ProfessionalCommission.objects.filter(
        tenant=professional.tenant,professional=professional,created_at__gte=month_start
    ).exclude(status=ProfessionalCommission.Status.REVERSED)
    pending=month_commissions.filter(status=ProfessionalCommission.Status.PENDING).aggregate(
        amount=Sum("commission_amount"))["amount"] or Decimal("0")
    paid=month_commissions.filter(status=ProfessionalCommission.Status.PAID).aggregate(
        amount=Sum("commission_amount"))["amount"] or Decimal("0")
    projected=Decimal("0")
    if professional.commission_percent is not None:
        for item in upcoming:
            projected+=(item.service_price_snapshot if item.service_price_snapshot is not None
                        else item.service.price)*professional.commission_percent/Decimal("100")
    return render(request,"portal/professional_area.html",{
        "professional":professional,"upcoming":upcoming[:15],"upcoming_count":upcoming.count(),
        "completed_month":appointments.filter(starts_at__gte=month_start,starts_at__lt=now,
                                               status=Appointment.Status.COMPLETED).count(),
        "pending_commission":pending,"paid_commission":paid,
        "projected_commission":projected,"has_projection":professional.commission_percent is not None,
    })
