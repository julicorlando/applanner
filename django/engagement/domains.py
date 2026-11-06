import secrets

import dns.resolver
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import TenantDomain


def create_tenant_domain(*,tenant,domain):
    domain=(domain or "").strip().lower().rstrip(".")
    if not domain or "." not in domain or "/" in domain or ":" in domain:
        raise ValidationError("Informe apenas o domínio, por exemplo agenda.exemplo.com.br.")
    row,created=TenantDomain.objects.get_or_create(
        domain=domain,
        defaults={
            "tenant":tenant,
            "status":TenantDomain.Status.PENDING,
            "verification_token":secrets.token_hex(24),
        },
    )
    if not created and row.tenant_id!=tenant.id:
        raise ValidationError("Este domínio já está em uso.")
    if not row.verification_token:
        row.verification_token=secrets.token_hex(24)
        row.status=TenantDomain.Status.PENDING
        row.save(update_fields=["verification_token","status","updated_at"])
    return row


def verify_tenant_domain(domain_row):
    expected=f"applanner-verification={domain_row.verification_token}"
    name=f"_applanner.{domain_row.domain}"
    try:
        answers=dns.resolver.resolve(name,"TXT",lifetime=8)
        values=[]
        for answer in answers:
            raw=b"".join(getattr(answer,"strings",[]) or [])
            values.append(raw.decode("utf-8") if raw else str(answer).strip('"'))
        ok=expected in values
    except Exception:
        ok=False
    domain_row.status=TenantDomain.Status.VERIFIED if ok else TenantDomain.Status.PENDING
    domain_row.verified_at=timezone.now() if ok else None
    domain_row.save(update_fields=["status","verified_at","updated_at"])
    return ok
