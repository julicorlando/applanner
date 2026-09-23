from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.db.models import Q
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .models import LoginAudit, LoginHistory, SecurityEvent
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
