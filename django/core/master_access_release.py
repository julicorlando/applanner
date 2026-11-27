"""Master flow to release a company's access, one user at a time, with a welcome e-mail.

Each release issues a single-use link for the user to create the password. The e-mail is sent
synchronously so the Master gets an immediate confirmation (or the SMTP reason it failed).
"""

import hashlib
import secrets
import smtplib
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from applanner.transactional_email import render_email

from .master import _guard

TEMPLATE_KEY = "access_release"
LINK_HOURS = 72
RESEND_PAUSE = timedelta(seconds=60)


def _base_url(request):
    return (getattr(settings, "PUBLIC_BASE_URL", "") or request.build_absolute_uri("/")).rstrip("/")


def _absolute(base, path):
    return path if path.startswith(("https://", "http://")) else base + path


def _assets(base):
    return {
        "logo": _absolute(base, static("images/applanner-logo.png")),
        "card": _absolute(base, static("images/email/welcome-dashboard.jpg")),
    }


def _last_releases(tenant, emails):
    from communications.models import Notification

    latest = {}
    rows = Notification.objects.filter(
        tenant=tenant, channel=Notification.Channel.EMAIL, template_key=TEMPLATE_KEY,
        destination__in=emails,
    ).order_by("-created_at", "-pk")
    for row in rows:
        latest.setdefault(row.destination.lower(), row)
    return latest


@login_required
@never_cache
def companies(request):
    from tenants.models import Tenant

    _guard(request.user)
    query = (request.GET.get("q") or "").strip()
    rows = Tenant.objects.filter(deleted_at__isnull=True, archived_at__isnull=True)
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(slug__icontains=query))
    rows = rows.annotate(
        user_count=Count("users", filter=Q(users__deleted_at__isnull=True), distinct=True),
    ).order_by("name")[:200]
    return render(request, "master/access_release_companies.html", {"companies": rows, "query": query})


@login_required
@never_cache
def company(request, pk):
    from accounts.models import User
    from tenants.models import Tenant

    _guard(request.user)
    tenant = get_object_or_404(Tenant, pk=pk, deleted_at__isnull=True)
    users = list(User.objects.filter(tenant=tenant, deleted_at__isnull=True)
                 .order_by("-is_active", "role", "first_name", "email"))
    latest = _last_releases(tenant, [user.email for user in users if user.email])
    rows = []
    for user in users:
        notice = latest.get((user.email or "").lower())
        rows.append({
            "user": user,
            "notice": notice,
            "password_ready": bool(user.password_changed_at or user.last_login),
            "can_release": bool(user.is_active and user.email),
        })
    return render(request, "master/access_release_company.html", {
        "tenant": tenant, "rows": rows, "link_hours": LINK_HOURS,
        "released": sum(1 for row in rows if row["notice"] and row["notice"].status == "sent"),
    })


@login_required
@require_POST
def release(request, pk, user_pk):
    from accounts.models import PasswordResetToken, User
    from communications.models import Notification
    from tenants.models import Tenant

    from .master_email import smtp_failure_reason
    from .models import AuditLog

    _guard(request.user)
    tenant = get_object_or_404(Tenant, pk=pk, deleted_at__isnull=True)
    user = get_object_or_404(User, pk=user_pk, tenant=tenant, deleted_at__isnull=True)
    back = redirect(reverse("master-access-release-company", args=[tenant.pk]) + f"#usuario-{user.pk}")
    if not user.is_active or not user.email:
        messages.error(request, f"{user.email or 'Usuário'} está inativo ou sem e-mail. Ative o cadastro antes de liberar o acesso.")
        return back
    recent = Notification.objects.filter(
        tenant=tenant, channel=Notification.Channel.EMAIL, template_key=TEMPLATE_KEY,
        destination__iexact=user.email, status=Notification.Status.SENT,
        sent_at__gte=timezone.now() - RESEND_PAUSE,
    ).exists()
    if recent:
        messages.info(request, f"O e-mail para {user.email} acabou de ser enviado. Aguarde um minuto antes de reenviar.")
        return back

    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    raw = secrets.token_urlsafe(32)
    token = PasswordResetToken.objects.create(
        user=user, token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=timezone.now() + timedelta(hours=LINK_HOURS),
    )
    base = _base_url(request)
    link = base + reverse("accounts:password-reset-confirm", args=[raw])
    subject, text, html = render_email(TEMPLATE_KEY, {
        "nome": user.first_name or user.email.split("@")[0],
        "empresa": tenant.name,
        "email": user.email,
        "url_senha": link,
        "validade": f"{LINK_HOURS // 24} dias",
        "_assets": _assets(base),
    })
    # The stored copy never keeps the live link: the token only exists in the user's inbox.
    stored = {"subject": subject, "user_id": user.pk, "released_by": request.user.pk}
    try:
        message = EmailMultiAlternatives(subject=subject, body=text, from_email=settings.DEFAULT_FROM_EMAIL, to=[user.email])
        message.attach_alternative(html, "text/html")
        if message.send(fail_silently=False) != 1:
            raise RuntimeError("SMTP não confirmou o envio")
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        token.delete()
        reason = smtp_failure_reason(exc)
        Notification.objects.create(
            tenant=tenant, channel=Notification.Channel.EMAIL, destination=user.email,
            template_key=TEMPLATE_KEY, payload=stored, status=Notification.Status.FAILED,
            error_message=reason[:500],
        )
        messages.error(request, f"Não foi possível enviar o e-mail para {user.email}. {reason}")
        return back
    now = timezone.now()
    Notification.objects.create(
        tenant=tenant, channel=Notification.Channel.EMAIL, destination=user.email,
        template_key=TEMPLATE_KEY, payload=stored, status=Notification.Status.SENT, sent_at=now,
    )
    AuditLog.objects.create(
        tenant=tenant, user=request.user, action="MASTER_ACCESS_RELEASED", entity_type="user",
        entity_id=user.pk, after={"email": user.email, "link_hours": LINK_HOURS},
    )
    messages.success(request, f"Acesso liberado. E-mail de boas-vindas enviado para {user.email}.")
    return back
