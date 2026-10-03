from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Capability


LEGACY_ROLE_CAPABILITIES={
    "master":{"*"},
    "owner":{"agenda.manage","finance.manage","barber.manage","arena.manage","auto.manage","engagement.manage","healthcare.manage","communications.manage","support.manage"},
    "manager":{"agenda.manage","finance.manage","barber.manage","arena.manage","auto.manage","engagement.manage","healthcare.manage","support.manage"},
    "reception":{"agenda.manage","engagement.manage","communications.manage","support.manage","barber.manage","arena.manage","auto.manage"},
    "professional":{"agenda.manage","barber.manage","arena.manage","auto.manage","healthcare.manage","communications.manage","support.manage"},
    "commercial":{"commercial.manage","communications.manage"},
    "finance":{"finance.manage"},
    "barber-manager":{"agenda.manage","barber.manage","finance.manage","engagement.manage"},
    "arena-manager":{"arena.manage","finance.manage","engagement.manage"},
    "auto-manager":{"agenda.manage","auto.manage","finance.manage","engagement.manage"},
    "healthcare":{"agenda.manage","healthcare.manage","support.manage"},
    "tenant-admin":{"agenda.manage","finance.manage","barber.manage","arena.manage","auto.manage","engagement.manage","healthcare.manage","support.manage"},
    "support":{"support.manage","master.support.impersonate"},
    "user":{"agenda.manage","communications.manage","support.manage"},
}


def user_capabilities(user):
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"*"}
    linked=set(
        Capability.objects.filter(
            role_links__role__user_links__user=user
        ).values_list("slug",flat=True).distinct()
    )
    linked.update(LEGACY_ROLE_CAPABILITIES.get(getattr(user,"role",""),set()))
    if getattr(user,"role","")=="commercial":
        from commercial.models import CommercialProfile
        if CommercialProfile.objects.filter(
            user=user,active=True,support_enabled=True
        ).exists():
            linked.add("support.manage")
    return linked


def has_capability(user,slug):
    caps=user_capabilities(user)
    return "*" in caps or slug in caps


def require_capability(slug):
    def decorator(view):
        @wraps(view)
        def wrapped(request,*args,**kwargs):
            if not has_capability(request.user,slug):
                raise PermissionDenied(f"Permissão necessária: {slug}")
            return view(request,*args,**kwargs)
        return wrapped
    return decorator


class CapabilityPermission(BasePermission):
    required_capability=None

    def has_permission(self,request,view):
        slug=getattr(view,"required_capability",None) or self.required_capability
        return bool(slug and has_capability(request.user,slug))


def require_any_capability(user,*slugs):
    if not any(has_capability(user,slug) for slug in slugs):
        raise PermissionDenied("Permissão insuficiente.")
