"""Shared-cache attempt budgets for password and second-factor verification."""
import hashlib
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse


def attempt_budget(request,kind,identity):
    window=max(1,int(getattr(settings,"AUTH_ATTEMPT_WINDOW_SECONDS",300)))
    default=10 if kind=="login" else 5
    limit=max(1,int(getattr(settings,"LOGIN_ATTEMPT_LIMIT" if kind=="login" else "TWO_FACTOR_ATTEMPT_LIMIT",default)))
    now=int(time.time())
    remaining=window-(now%window)
    # Do not retain submitted e-mail addresses or trust arbitrary forwarded headers.
    material=f"{request.META.get('REMOTE_ADDR','')}\0{str(identity).strip().lower()}"
    digest=hashlib.sha256(material.encode()).hexdigest()
    key=f"auth-attempt:{kind}:{now//window}:{digest}"
    if cache.add(key,1,timeout=remaining+1):
        count=1
    else:
        try:
            count=cache.incr(key)
        except ValueError:
            # A cache eviction between add and incr must not crash authentication.
            if cache.add(key,1,timeout=remaining+1):
                count=1
            else:
                count=cache.incr(key)
    return key,remaining if count>limit else 0


def clear_budget(key):
    cache.delete(key)


def limited_response(wait):
    response=HttpResponse(
        "Muitas tentativas. Aguarde alguns minutos e tente novamente.",
        status=429,content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"]=str(wait)
    return response
