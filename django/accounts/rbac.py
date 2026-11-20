from django.core.exceptions import PermissionDenied


def capability_slugs(user):
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {"*"}
    return set(
        user.role_links
        .filter(role__capability_links__isnull=False)
        .values_list("role__capability_links__capability__slug",flat=True)
        .distinct()
    )


def has_capability(user,slug):
    slugs=capability_slugs(user)
    return "*" in slugs or slug in slugs


def require_capability(user,slug):
    if not has_capability(user,slug):
        raise PermissionDenied(f"Permissão necessária: {slug}")
