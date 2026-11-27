from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from accounts.permissions import require_any_capability
from .models import BarberCommand
from .portal import _tenant


@login_required
@never_cache
def receipt(request, pk):
    require_any_capability(request.user, "barber.manage")
    tenant = _tenant(request)
    command = get_object_or_404(
        BarberCommand.objects.select_related(
            "customer", "professional"
        ).prefetch_related("items", "payments"),
        tenant=tenant,
        pk=pk,
    )
    return render(
        request, "barber/receipt.html", {"tenant": tenant, "command": command}
    )
