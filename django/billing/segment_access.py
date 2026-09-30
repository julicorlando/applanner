import unicodedata

from django.core.exceptions import PermissionDenied

from .entitlements import active_subscription, module_enabled
from .models import TenantModule


def segment_enabled(tenant, segment):
    category=unicodedata.normalize("NFKD", tenant.category or "").encode("ascii", "ignore").decode().lower()
    aliases={
        "barbearia": ("barber", "barbear", "salao", "cabel"),
        "arena": ("arena", "esport", "quadra"),
        "auto": ("auto", "lava", "detailing", "veicul"),
        "saude": ("saude", "clinic", "odonto", "dent"),
    }
    if not any(word in category for word in aliases[segment]):
        return False
    subscription=active_subscription(tenant)
    if subscription and "segments" in (subscription.plan.features or {}):
        if segment not in subscription.plan.features["segments"]:
            # Uma liberação explícita pelo Master prevalece sobre o catálogo do plano.
            if segment!="arena" or not TenantModule.objects.filter(
                tenant=tenant,module__slug="sports_courts",module__active=True,enabled=True
            ).exists():
                return False
    if segment=="arena" and subscription:
        return module_enabled(tenant,"sports_courts")
    return True


def require_segment(tenant, segment):
    if not segment_enabled(tenant, segment):
        raise PermissionDenied("Este módulo não está disponível para este estabelecimento.")


def require_feature(tenant,module_slug):
    if active_subscription(tenant) and not module_enabled(tenant,module_slug):
        raise PermissionDenied("Esta função não está incluída no plano da empresa.")
