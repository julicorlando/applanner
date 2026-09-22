from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Capability,RoleCapability,UserRole


LEGACY_ROLE_CAPABILITIES={
    "master":{"*"},
    "support":{"support.manage"},
    "owner":{"*tenant"},
    "manager":{"*tenant"},
    "reception":{"agenda.manage","engagement.manage","support.manage","arena.manage","auto.manage"},
    "finance":{"finance.manage"},
    "professional":{"agenda.manage","barber.manage","auto.manage","healthcare.manage","support.manage"},
    "commercial":{"commercial.manage"},
}


def user_capabilities(user):
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"*"}
    return set(
        Capability.objects.filter(
            role_links__role__user_links__user=user
        ).values_list("slug",flat=True).distinct()
    )


def has_capability(user,slug):
    caps=user_capabilities(user)
    if "*" in caps or slug in caps:
        return True
    role=(getattr(user,"role","") or "").lower()
    fallback=LEGACY_ROLE_CAPABILITIES.get(role,set())
    if "*" in fallback:
        return True
    if "*tenant" in fallback and getattr(user,"tenant_id",None):
        return True
    return slug in fallback


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
