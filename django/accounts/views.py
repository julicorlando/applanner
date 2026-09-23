import hashlib
import secrets
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.shortcuts import redirect, render
from django.utils import timezone
from django.db.models import Q
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import EmailVerificationToken, LoginAudit, LoginHistory, PasswordResetToken, SecurityEvent
from .security import (
    consume_recovery_code, decrypt_secret, encrypt_secret, generate_recovery_codes,
    generate_totp_secret, issue_trusted_device, validate_trusted_device, verify_totp,
)

User=get_user_model()
TRUSTED_COOKIE="applanner_trusted_device"

def _record_login_event(request,email,*,user=None,result="failed",reason=""):
    ip=request.META.get("REMOTE_ADDR") or None
    agent=(request.META.get("HTTP_USER_AGENT") or "")[:500]
    LoginAudit.objects.create(
        tenant=getattr(user,"tenant",None),user=user,email_attempted=email or "",
        event_type="login",result=result,ip_address=ip,user_agent=agent,
        failure_reason_code=reason[:60],
    )
    LoginHistory.objects.create(
        user=user,email=email or "",successful=result=="success",
        ip_address=ip,user_agent=agent,
    )



@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    if request.method=="POST":
        email=(request.POST.get("email") or "").strip().lower()
        password=request.POST.get("password") or ""
        user=authenticate(request,email=email,password=password)
        if not user:
            candidate=User.objects.filter(email=email).first()
            _record_login_event(request,email,user=candidate,result="failed",reason="invalid_credentials")
            messages.error(request,"E-mail ou senha inválidos.")
            return render(request,"accounts/login.html",status=400)
        if not user.is_active:
            _record_login_event(request,email,user=user,result="blocked",reason="inactive")
            messages.error(request,"Conta inativa.")
            return render(request,"accounts/login.html",status=403)

        active_block=user.blocks.filter(unblocked_at__isnull=True).filter(
            Q(expires_at__isnull=True)|Q(expires_at__gt=timezone.now())
        ).first()
        if active_block:
            _record_login_event(request,email,user=user,result="blocked",reason=active_block.reason_code)
            SecurityEvent.objects.create(
                tenant=user.tenant,user=user,event_type="blocked_login",
                severity=SecurityEvent.Severity.MEDIUM,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
                metadata={"reason_code":active_block.reason_code},
            )
            messages.error(request,"Acesso temporariamente bloqueado. Contate o suporte.")
            return render(request,"accounts/login.html",status=403)

        trusted=request.COOKIES.get(TRUSTED_COOKIE,"")
        if user.two_factor_enabled and not (trusted and validate_trusted_device(user,trusted)):
            _record_login_event(request,email,user=user,result="challenge",reason="two_factor")
            request.session["pre_2fa_user_id"]=user.pk
            request.session["pre_2fa_remember"]=bool(request.POST.get("remember_device"))
            request.session.cycle_key()
            return redirect("accounts:two-factor-challenge")

        login(request,user,backend="django.contrib.auth.backends.ModelBackend")
        request.session["session_version"]=user.session_version
        _record_login_event(request,email,user=user,result="success")
        return redirect(request.GET.get("next") or settings.LOGIN_REDIRECT_URL)
    return render(request,"accounts/login.html")


@never_cache
def two_factor_challenge(request):
    user_id=request.session.get("pre_2fa_user_id")
    if not user_id:
        return redirect("accounts:login")
    user=User.objects.filter(pk=user_id,is_active=True).first()
    if not user or not user.two_factor_enabled:
        request.session.pop("pre_2fa_user_id",None)
        return redirect("accounts:login")

    if request.method=="POST":
        code=(request.POST.get("code") or "").strip().replace(" ","")
        ok=False
        step=None
        try:
            secret=decrypt_secret(user.two_factor_secret_encrypted)
            step=verify_totp(secret,code,last_step=user.two_factor_last_step)
            ok=step is not None
        except Exception:
            ok=False
        if not ok:
            ok=consume_recovery_code(user,code)
        if not ok:
            messages.error(request,"Código inválido ou já utilizado.")
            return render(request,"accounts/two_factor_challenge.html",status=400)

        if step is not None:
            user.two_factor_last_step=step
            user.save(update_fields=["two_factor_last_step"])

        remember=bool(request.session.pop("pre_2fa_remember",False))
        request.session.pop("pre_2fa_user_id",None)
        login(request,user,backend="django.contrib.auth.backends.ModelBackend")
        request.session["session_version"]=user.session_version
        response=redirect(settings.LOGIN_REDIRECT_URL)
        if remember:
            token=issue_trusted_device(
                user,
                label="Navegador confiável",
                user_agent=request.META.get("HTTP_USER_AGENT",""),
                ip_address=request.META.get("REMOTE_ADDR") or None,
            )
            response.set_cookie(
                TRUSTED_COOKIE,token,
                max_age=settings.TRUSTED_DEVICE_DAYS*86400,
                secure=not settings.DEBUG,httponly=True,samesite="Lax",
            )
        return response
    return render(request,"accounts/two_factor_challenge.html")


@login_required
@never_cache
def two_factor_setup(request):
    if request.user.two_factor_enabled:
        return render(request,"accounts/two_factor_setup.html",{"enabled":True})
    secret=request.session.get("two_factor_setup_secret")
    if not secret:
        secret=generate_totp_secret()
        request.session["two_factor_setup_secret"]=secret
    issuer=quote("ApPlanner")
    account=quote(request.user.email)
    provisioning_uri=f"otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}&digits=6&period=30"

    if request.method=="POST":
        code=(request.POST.get("code") or "").strip()
        step=verify_totp(secret,code,last_step=0)
        if step is None:
            messages.error(request,"Código inválido. Confira o horário do autenticador.")
        else:
            request.user.two_factor_secret_encrypted=encrypt_secret(secret)
            request.user.two_factor_enabled_at=timezone.now()
            request.user.two_factor_last_step=step
            request.user.session_version+=1
            request.user.save(update_fields=[
                "two_factor_secret_encrypted","two_factor_enabled_at",
                "two_factor_last_step","session_version",
            ])
            request.session["session_version"]=request.user.session_version
            codes=generate_recovery_codes(request.user)
            request.session.pop("two_factor_setup_secret",None)
            return render(request,"accounts/recovery_codes.html",{"codes":codes})
    return render(request,"accounts/two_factor_setup.html",{
        "enabled":False,"secret":secret,"provisioning_uri":provisioning_uri,
    })


@login_required
@require_POST
def two_factor_disable(request):
    password=request.POST.get("password") or ""
    if not request.user.check_password(password):
        messages.error(request,"Senha atual inválida.")
        return redirect("accounts:two-factor-setup")
    request.user.two_factor_secret_encrypted=""
    request.user.two_factor_enabled_at=None
    request.user.two_factor_last_step=0
    request.user.session_version+=1
    request.user.save(update_fields=[
        "two_factor_secret_encrypted","two_factor_enabled_at",
        "two_factor_last_step","session_version",
    ])
    request.session["session_version"]=request.user.session_version
    request.user.recovery_codes.all().delete()
    request.user.trusted_devices.all().delete()
    response=redirect("accounts:two-factor-setup")
    response.delete_cookie(TRUSTED_COOKIE)
    messages.success(request,"Autenticação em duas etapas desativada.")
    return response


@require_POST
def logout_view(request):
    logout(request)
    response=redirect(settings.LOGOUT_REDIRECT_URL)
    response.delete_cookie(TRUSTED_COOKIE)
    return response


@never_cache
def password_reset_request(request):
    if request.method=="POST":
        email=(request.POST.get("email") or "").strip().lower()
        user=User.objects.filter(email=email,is_active=True).first()
        if user:
            PasswordResetToken.objects.filter(user=user,used_at__isnull=True).update(used_at=timezone.now())
            raw=secrets.token_urlsafe(32)
            PasswordResetToken.objects.create(
                user=user,
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=timezone.now()+timedelta(hours=1),
            )
            url=request.build_absolute_uri(
                f"/account/password-reset/{raw}/"
            )
            send_mail(
                "Redefinição de senha — ApPlanner",
                f"Use este link em até 1 hora para redefinir sua senha: {url}",
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        messages.success(request,"Se o e-mail estiver cadastrado, enviaremos as instruções de recuperação.")
        return redirect("accounts:password-reset-request")
    return render(request,"accounts/password_reset_request.html")


@never_cache
def password_reset_confirm(request,token):
    digest=hashlib.sha256(token.encode()).hexdigest()
    row=PasswordResetToken.objects.select_related("user").filter(
        token_hash=digest,used_at__isnull=True,expires_at__gt=timezone.now()
    ).first()
    if not row:
        messages.error(request,"Link de recuperação inválido ou expirado.")
        return redirect("accounts:password-reset-request")
    if request.method=="POST":
        password=request.POST.get("password") or ""
        confirmation=request.POST.get("password_confirmation") or ""
        if len(password)<8:
            messages.error(request,"A nova senha deve ter pelo menos 8 caracteres.")
        elif password!=confirmation:
            messages.error(request,"As senhas não conferem.")
        else:
            user=row.user
            user.set_password(password)
            user.password_changed_at=timezone.now()
            user.must_change_password=False
            user.session_version+=1
            user.save(update_fields=["password","password_changed_at","must_change_password","session_version"])
            row.used_at=timezone.now()
            row.save(update_fields=["used_at"])
            user.trusted_devices.all().delete()
            messages.success(request,"Senha redefinida. Faça login com a nova senha.")
            return redirect("accounts:login")
    return render(request,"accounts/password_reset_confirm.html",{"token":token})


@login_required
@require_POST
def send_verification(request):
    if request.user.email_verified_at:
        messages.info(request,"Seu e-mail já está verificado.")
        return redirect(settings.LOGIN_REDIRECT_URL)
    EmailVerificationToken.objects.filter(user=request.user,used_at__isnull=True).update(used_at=timezone.now())
    raw=secrets.token_urlsafe(32)
    EmailVerificationToken.objects.create(
        user=request.user,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=timezone.now()+timedelta(hours=24),
    )
    url=request.build_absolute_uri(f"/account/verify-email/{raw}/")
    send_mail(
        "Verifique seu e-mail — ApPlanner",
        f"Confirme seu e-mail usando este link em até 24 horas: {url}",
        settings.DEFAULT_FROM_EMAIL,
        [request.user.email],
        fail_silently=False,
    )
    messages.success(request,"Link de verificação enviado.")
    return redirect(settings.LOGIN_REDIRECT_URL)


@never_cache
def verify_email(request,token):
    digest=hashlib.sha256(token.encode()).hexdigest()
    row=EmailVerificationToken.objects.select_related("user").filter(
        token_hash=digest,used_at__isnull=True,expires_at__gt=timezone.now()
    ).first()
    if not row:
        messages.error(request,"Link de verificação inválido ou expirado.")
        return redirect("accounts:login")
    now=timezone.now()
    row.used_at=now
    row.save(update_fields=["used_at"])
    row.user.email_verified_at=now
    row.user.save(update_fields=["email_verified_at"])
    messages.success(request,"E-mail verificado com sucesso.")
    return redirect("accounts:login")


@login_required
@never_cache
def change_password(request):
    if request.method=="POST":
        current=request.POST.get("current_password") or ""
        password=request.POST.get("password") or ""
        confirmation=request.POST.get("password_confirmation") or ""
        if not request.user.check_password(current):
            messages.error(request,"Senha atual inválida.")
        elif password!=confirmation:
            messages.error(request,"As novas senhas não conferem.")
        else:
            try:
                validate_password(password,user=request.user)
            except ValidationError as exc:
                for item in exc.messages:
                    messages.error(request,item)
            else:
                request.user.set_password(password)
                request.user.password_changed_at=timezone.now()
                request.user.must_change_password=False
                request.user.session_version+=1
                request.user.save(update_fields=[
                    "password","password_changed_at","must_change_password","session_version",
                ])
                request.session["session_version"]=request.user.session_version
                request.user.trusted_devices.all().delete()
                messages.success(request,"Senha atualizada com sucesso.")
                return redirect(settings.LOGIN_REDIRECT_URL)
    return render(request,"accounts/change_password.html",{
        "required":request.user.must_change_password,
    })
