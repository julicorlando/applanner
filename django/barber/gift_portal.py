import secrets
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from accounts.permissions import require_any_capability
from finance.market_portal import GiftRedeemForm
from finance.giftcards import redeem
from .portal import _tenant
from .models import BarberCommand


@login_required
def use_gift(request, pk):
    require_any_capability(request.user, "barber.manage")
    if request.user.role == "professional":
        raise PermissionDenied
    tenant = _tenant(request)
    command = get_object_or_404(BarberCommand, tenant=tenant, pk=pk, status="open")
    form = GiftRedeemForm(
        request.POST or None,
        initial={"command": command.pk, "key": secrets.token_urlsafe(24)},
    )
    form.fields["command"].queryset = BarberCommand.objects.filter(
        tenant=tenant, pk=pk, status="open"
    )
    form.fields["command"].widget = forms.HiddenInput()
    if request.method == "POST" and form.is_valid():
        try:
            redeem(tenant=tenant, user=request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else "Identificador já utilizado.",
            )
        else:
            messages.success(request, "Vale aplicado ao pagamento da comanda.")
            return redirect("barber-command-detail", pk=pk)
    return render(
        request, "barber/gift_payment.html", {"form": form, "command": command}
    )
