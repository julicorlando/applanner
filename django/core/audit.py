from decimal import Decimal
from django.db.models import Model

from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    forwarded=(request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or None


def request_user_agent(request):
    return ((request.META.get("HTTP_USER_AGENT") or "")[:500] if request else "")


def _safe(value):
    if isinstance(value,Decimal):
        return str(value)
    if hasattr(value,"isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value,(str,int,float,bool)) or value is None:
        return value
    if isinstance(value,(list,tuple,set)):
        return [_safe(item) for item in value]
    if isinstance(value,dict):
        return {str(key):_safe(item) for key,item in value.items()}
    return str(value)


def model_snapshot(obj,fields=None):
    if obj is None:
        return None
    names=fields or [field.name for field in obj._meta.concrete_fields]
    sensitive_tokens=("password","secret","token","encrypted","credential","pix_key")
    data={}
    for name in names:
        if any(token in name.lower() for token in sensitive_tokens):
            continue
        try:
            value=getattr(obj,name)
        except Exception:
            continue
        if isinstance(value,Model):
            value=value.pk
        data[name]=_safe(value)
    return data


def append_audit(
    *,tenant=None,user=None,action,entity_type="",entity_id=None,
    before=None,after=None,request=None,
):
    return AuditLog.objects.create(
        tenant=tenant,
        user=user,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=client_ip(request),
        user_agent=request_user_agent(request),
        before=_safe(before),
        after=_safe(after),
    )
