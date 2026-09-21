from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Capability,RoleCapability,UserRole


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
