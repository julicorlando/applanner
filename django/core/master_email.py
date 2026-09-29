"""Master-only mail settings and per-tenant onboarding exception."""

import logging
import smtplib
import socket
import ssl

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.models import User
from core.crypto import encrypt_text
from core.models import AuditLog
from operations.models import PlatformSMTPSettings
from tenants.models import TenantOnboarding

logger=logging.getLogger(__name__)


def smtp_failure_reason(exc):
    """Return a useful diagnosis without exposing server responses or credentials."""
    if isinstance(exc,smtplib.SMTPAuthenticationError):
        return "Autenticação SMTP recusada. Confira o usuário completo e a senha da caixa postal."
    if isinstance(exc,ssl.SSLError):
        return "Falha na negociação SSL/TLS. Confira a porta e o modo de segurança."
    if isinstance(exc,socket.gaierror):
        return "Servidor SMTP não encontrado. Confira o endereço do servidor e o DNS."
    if isinstance(exc,(TimeoutError,ConnectionRefusedError,ConnectionResetError)):
        return "Não foi possível conectar ao servidor SMTP. Confira a porta e a liberação da conexão de saída."
    if isinstance(exc,smtplib.SMTPResponseException):
        if exc.smtp_code in (550,553):
            return f"Remetente ou destinatário recusado pelo servidor SMTP (código {exc.smtp_code})."
        return f"O servidor SMTP recusou o envio (código {exc.smtp_code})."
    if isinstance(exc,OSError):
        return "Falha de conexão com o servidor SMTP. Confira o host, a porta e a rede."
    return "O servidor SMTP não confirmou o envio. Confira as configurações e os logs do web."


class MasterSMTPForm(forms.Form):
    host=forms.CharField(max_length=255,label="Servidor SMTP",widget=forms.TextInput(attrs={"placeholder":"smtp.exemplo.com.br","autocomplete":"off"}))
    port=forms.IntegerField(min_value=1,max_value=65535,label="Porta SMTP",initial=587)
    username=forms.CharField(max_length=255,required=False,label="Usuário SMTP")
    password=forms.CharField(required=False,label="Senha SMTP",widget=forms.PasswordInput(attrs={"autocomplete":"new-password"}))
    from_email=forms.EmailField(label="E-mail remetente")
    use_tls=forms.BooleanField(required=False,label="STARTTLS (normalmente porta 587)",initial=True)
    use_ssl=forms.BooleanField(required=False,label="SSL direto (normalmente porta 465)")
    enabled=forms.BooleanField(required=False,label="Ativar esta configuração")

    def __init__(self,*args,existing=None,**kwargs):
        self.existing=existing
        if not args and existing:
            kwargs.setdefault("initial",{
                key:getattr(existing,key) for key in ("host","port","username","from_email","use_tls","use_ssl","enabled")
            })
        super().__init__(*args,**kwargs)

    def clean(self):
        values=super().clean()
        if values.get("use_tls") and values.get("use_ssl"):
            raise forms.ValidationError("Use STARTTLS ou SSL direto; não ative os dois.")
        retained=bool(self.existing and values.get("username")==self.existing.username and self.existing.password_encrypted)
        if bool(values.get("username"))!=bool(values.get("password") or retained):
            raise forms.ValidationError("Informe usuário e senha SMTP juntos.")
        return values


@login_required
@never_cache
def smtp_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")
    row=PlatformSMTPSettings.objects.filter(pk=1).first()
    form=(MasterSMTPForm(request.POST,existing=row) if request.method=="POST"
          else MasterSMTPForm(existing=row))
    if request.method=="POST":
        if request.POST.get("action")=="test":
            if not row or not row.enabled:
                messages.error(request,"Salve e ative as configurações SMTP antes do teste.")
            elif settings.EMAIL_BACKEND!="applanner.email_backend.PlatformEmailBackend":
                messages.error(request,"O backend de e-mail do Coolify não usa a configuração SMTP do painel. Ajuste EMAIL_BACKEND e publique novamente.")
            else:
                try:
                    sent=send_mail("Teste de e-mail — ApPlanner","O envio SMTP da plataforma está funcionando.",
                        row.from_email,[request.user.email],fail_silently=False)
                    if sent!=1:
                        raise RuntimeError("SMTP não confirmou o envio")
                except (OSError,smtplib.SMTPException,RuntimeError,ValueError) as exc:
                    reason=smtp_failure_reason(exc)
                    logger.warning("Teste SMTP do Master falhou: %s; tipo=%s; host=%s; porta=%s; ssl=%s; starttls=%s",
                        reason,type(exc).__name__,row.host,row.port,row.use_ssl,row.use_tls)
                    messages.error(request,f"O teste falhou. {reason}")
                else:
                    messages.success(request,f"E-mail de teste enviado para {request.user.email}.")
            return redirect("master-smtp-settings")
        if form.is_valid():
            values=form.cleaned_data
            with transaction.atomic():
                row,_=PlatformSMTPSettings.objects.select_for_update().get_or_create(pk=1,defaults={
                    "host":values["host"],"from_email":values["from_email"],
                })
                for field in ("host","port","username","from_email","use_tls","use_ssl","enabled"):
                    setattr(row,field,values[field])
                if values["password"]:
                    row.password_encrypted=encrypt_text(values["password"])
                elif not values["username"]:
                    row.password_encrypted=""
                row.updated_by=request.user
                row.full_clean()
                row.save()
                AuditLog.objects.create(user=request.user,action="MASTER_SMTP_UPDATED",
                    entity_type="platform_smtp_settings",entity_id=1,
                    after={"enabled":row.enabled,"host":row.host,"port":row.port,"from_email":row.from_email},
                    ip_address=request.META.get("REMOTE_ADDR") or None)
            messages.success(request,"Configuração SMTP salva. Envie um teste para verificar a entrega.")
            return redirect("master-smtp-settings")
    return render(request,"master/smtp_settings.html",{
        "form":form,"configured":row,"has_password":bool(row and row.password_encrypted),
        "backend_supported":settings.EMAIL_BACKEND=="applanner.email_backend.PlatformEmailBackend",
    })


@login_required
@require_POST
def waive_onboarding_email(request,pk):
    if not request.user.is_superuser:
        raise PermissionDenied("Acesso restrito ao Master.")
    with transaction.atomic():
        row=get_object_or_404(TenantOnboarding.objects.select_for_update().select_related("tenant"),pk=pk,required=True)
        if row.completed_at:
            messages.error(request,"O cadastro já está concluído; a dispensa não pode ser alterada aqui.")
        else:
            previous=bool(row.email_verification_waived_at)
            if request.POST.get("action")=="grant" and not previous:
                row.email_verification_waived_at=timezone.now()
                row.email_verification_waived_by=request.user
                row.save(update_fields=["email_verification_waived_at","email_verification_waived_by","updated_at"])
                messages.success(request,"Confirmação de e-mail dispensada para este cadastro. A empresa ainda deve concluir as etapas.")
            elif request.POST.get("action")=="revoke" and previous:
                row.email_verification_waived_at=None
                row.email_verification_waived_by=None
                row.save(update_fields=["email_verification_waived_at","email_verification_waived_by","updated_at"])
                messages.success(request,"Dispensa revogada; o responsável deverá confirmar o e-mail.")
            else:
                return redirect("master-resource-list",slug="onboarding")
            AuditLog.objects.create(tenant=row.tenant,user=request.user,
                action="MASTER_EMAIL_VERIFICATION_WAIVER",entity_type="tenant_onboarding",entity_id=row.tenant_id,
                before={"waived":previous},after={"waived":bool(row.email_verification_waived_at)},
                ip_address=request.META.get("REMOTE_ADDR") or None)
    return redirect("master-resource-list",slug="onboarding")
