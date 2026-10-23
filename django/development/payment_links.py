"""A private reminder link plus document unlocks only its invoice, never an account."""

import hashlib
import re
import secrets
from datetime import timedelta
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db.models import F
from django.utils import timezone
from .models import PaymentLink

SALT = "development.invoice-access.v1"
SESSION_KEY = "development_invoice_grants"
GRANT_SECONDS = 12 * 60 * 60


def create_payment_link(charge, customer):
    from .services import public_url

    token = secrets.token_urlsafe(32)
    row = PaymentLink.objects.create(
        charge=charge,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        charge_revision=charge.revision,
        document_hash=customer.document_hash,
        expires_at=timezone.now() + timedelta(days=30),
    )
    return row, public_url("development-payment-link", token)


def valid_links():
    return PaymentLink.objects.select_related(
        "charge__client__user", "charge__bank"
    ).filter(
        expires_at__gt=timezone.now(),
        charge_revision=F("charge__revision"),
        document_hash=F("charge__client__document_hash"),
        charge__client__active=True,
        charge__client__user__is_active=True,
        charge__client__user__deleted_at__isnull=True,
    )


def find_link(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    return (
        valid_links()
        .filter(token_hash=hashlib.sha256(token.encode()).hexdigest())
        .first()
    )


def grant_access(request, link):
    grants = dict(request.session.get(SESSION_KEY, {}))
    grants.pop(str(link.charge_id), None)
    grants = dict(list(grants.items())[-9:])
    grants[str(link.charge_id)] = signing.dumps(
        {"link": link.pk, "charge": link.charge_id}, salt=SALT
    )
    request.session.cycle_key()
    request.session[SESSION_KEY] = grants


def granted_charge(request, pk):
    raw = request.session.get(SESSION_KEY, {}).get(str(pk))
    if not raw:
        return None
    try:
        data = signing.loads(raw, salt=SALT, max_age=GRANT_SECONDS)
    except (signing.BadSignature, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("charge") != pk:
        return None
    link = valid_links().filter(pk=data.get("link"), charge_id=pk).first()
    return link.charge if link else None


def payment_required(view):
    authenticated = login_required(view)

    @wraps(view)
    def wrapped(request, pk, *args, **kwargs):
        if not request.user.is_superuser:
            row = granted_charge(request, pk)
            if row:
                request.development_payment_charge = row
                request.development_public_payment = True
                return view(request, pk, *args, **kwargs)
        return authenticated(request, pk, *args, **kwargs)

    return wrapped
