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


def verify_audit_chain(chain_key=None):
    import hashlib
    import json
    from .models import AuditChainState

    qs=AuditLog.objects.order_by("chain_key","created_at","pk")
    if chain_key:
        qs=qs.filter(chain_key=chain_key)
    previous_by_chain={}
    checked=0
    for row in qs.iterator():
        key=row.chain_key or (f"tenant:{row.tenant_id}" if row.tenant_id else "platform")
        previous=previous_by_chain.get(key,"")
        payload=json.dumps({
            "tenant_id":row.tenant_id,
            "user_id":row.user_id,
            "action":row.action,
            "entity_type":row.entity_type,
            "entity_id":row.entity_id,
            "ip_address":str(row.ip_address or ""),
            "user_agent":row.user_agent or "",
            "before":row.before,
            "after":row.after,
            "created_at":row.created_at.isoformat() if row.created_at else "",
        },sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str)
        expected=hashlib.sha256((previous+"|"+payload).encode("utf-8")).hexdigest()
        if row.previous_hash!=previous or row.entry_hash!=expected:
            return {
                "valid":False,"checked":checked,
                "broken_id":row.pk,"chain_key":key,
            }
        previous_by_chain[key]=row.entry_hash
        checked+=1

    for key,last_hash in previous_by_chain.items():
        state=AuditChainState.objects.filter(chain_key=key).first()
        if not state or state.last_hash!=last_hash:
            return {
                "valid":False,"checked":checked,
                "broken_id":None,"chain_key":key,
            }
    return {"valid":True,"checked":checked,"broken_id":None,"chain_key":chain_key}
