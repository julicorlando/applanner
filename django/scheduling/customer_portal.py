"""Tenant-scoped customer portal; an appointment token never grants account access."""

import secrets
import time
from datetime import timedelta
from django import forms
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.cache import never_cache
from accounts.login_limits import attempt_budget, limited_response
from tenants.models import Tenant
from .models import Appointment, Customer, CustomerAccessChallenge


class EmailForm(forms.Form):
    email = forms.EmailField(
        label="E-mail cadastrado",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )


class CodeForm(forms.Form):
    code = forms.RegexField(
        r"^\d{6}$",
        label="Código de seis dígitos",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "maxlength": "6",
            }
        ),
    )


def tenant_for(slug):
    row = Tenant.objects.filter(
        Q(public_slug=slug) | Q(public_slug__isnull=True, slug=slug),
        public_enabled=True,
        status__in=["active", "trial"],
        deleted_at__isnull=True,
        archived_at__isnull=True,
    ).first()
    if not row:
        raise Http404
    return row


def identity_digest(customer):
    return salted_hmac(
        "customer-portal-identity",
        f"{customer.tenant_id}:{customer.pk}:{customer.email.strip().lower()}",
        algorithm="sha256",
    ).hexdigest()


def digest(challenge, code):
    return salted_hmac(
        "customer-portal-otp",
        f"{challenge.pk}:{identity_digest(challenge.customer) if challenge.customer_id else ''}:{code}",
        algorithm="sha256",
    ).hexdigest()


@never_cache
def portal(request, slug):
    tenant = tenant_for(slug)
    key = f"customer-portal:{tenant.pk}"
    access = request.session.get(key, {})
    customer = None
    if access.get("expires", 0) > time.time():
        customer = Customer.objects.filter(
            pk=access.get("customer"), tenant=tenant, active=True
        ).first()
    if customer and not constant_time_compare(
        access.get("identity", ""), identity_digest(customer)
    ):
        customer = None
        request.session.pop(key, None)
    if request.method == "POST" and request.POST.get("action") == "logout":
        request.session.pop(key, None)
        request.session.cycle_key()
        return redirect("customer-portal", slug=slug)
    if customer:
        from billing.entitlements import module_enabled
        from engagement.models import (
            CustomerMembership,
            CustomerPackage,
            LoyaltyAccount,
        )
        from arena.models import Reservation

        memberships = (
            CustomerMembership.objects.filter(
                tenant=tenant, customer=customer
            ).select_related("package")
            if module_enabled(tenant, "packages")
            else CustomerMembership.objects.none()
        )
        packages = (
            CustomerPackage.objects.filter(
                tenant=tenant, customer=customer
            ).select_related("package")
            if module_enabled(tenant, "packages")
            else CustomerPackage.objects.none()
        )
        loyalty = (
            LoyaltyAccount.objects.filter(tenant=tenant, customer=customer).first()
            if module_enabled(tenant, "loyalty")
            else None
        )
        appointments = (
            Appointment.objects.filter(tenant=tenant, customer=customer)
            .select_related("service", "professional", "unit")
            .order_by("-starts_at")[:100]
        )
        # Manage links belong only to this verified identity, decrypted server-side.
        from core.crypto import decrypt_text

        for row in appointments:
            token = (
                decrypt_text(row.customer_manage_token_encrypted)
                if row.customer_manage_token_encrypted
                else ""
            )
            row.portal_manage_url = (
                reverse("public-appointment-page", args=[token]) if token else ""
            )
        return render(
            request,
            "scheduling/customer_portal.html",
            {
                "tenant": tenant,
                "customer": customer,
                "appointments": appointments,
                "memberships": memberships[:50],
                "packages": packages[:50],
                "loyalty": loyalty,
                "reservations": Reservation.objects.filter(
                    tenant=tenant, customer=customer
                )
                .select_related("court")
                .order_by("-starts_at")[:100],
            },
        )
    form = EmailForm(
        request.POST
        if request.method == "POST" and request.POST.get("action") == "send"
        else None
    )
    code_form = CodeForm(
        request.POST
        if request.method == "POST" and request.POST.get("action") == "verify"
        else None
    )
    challenge_key = f"customer-challenge:{tenant.pk}"
    pending = request.session.get(challenge_key)
    notice = ""
    if request.method == "POST":
        _, wait = attempt_budget(request, "customer-portal-global", tenant.pk)
        if wait:
            return limited_response(wait)
        if request.POST.get("action") == "send" and form.is_valid():
            email = form.cleaned_data["email"].strip().lower()
            _, wait = attempt_budget(request, "customer-portal-email", email)
            if wait:
                return limited_response(wait)
            matches = list(
                Customer.objects.filter(
                    tenant=tenant, active=True, email__iexact=email
                )[:2]
            )
            candidate = matches[0] if len(matches) == 1 else None
            code = f"{secrets.randbelow(1000000):06d}"
            with transaction.atomic():
                if pending:
                    CustomerAccessChallenge.objects.filter(
                        pk=pending, tenant=tenant
                    ).update(used_at=timezone.now())
                row = CustomerAccessChallenge(
                    tenant=tenant,
                    customer=candidate,
                    expires_at=timezone.now() + timedelta(minutes=10),
                )
                row.code_digest = digest(row, code)
                row.save()
            pending = str(row.pk)
            request.session[challenge_key] = pending
            # The response remains identical for unknown, ambiguous or undeliverable emails.
            if candidate:
                try:
                    send_mail(
                        "Seu código de acesso · ApPlanner",
                        f"Código para acessar seus agendamentos em {tenant.name}: {code}. Expira em 10 minutos. Não compartilhe este código.",
                        None,
                        [candidate.email],
                    )
                except Exception:
                    pass
            notice = "Se esse e-mail estiver cadastrado, você receberá um código válido por 10 minutos. Confira também o spam."
        elif (
            request.POST.get("action") == "verify" and code_form.is_valid() and pending
        ):
            with transaction.atomic():
                row = (
                    CustomerAccessChallenge.objects.select_for_update()
                    .filter(pk=pending, tenant=tenant)
                    .first()
                )
                valid = (
                    row
                    and not row.used_at
                    and row.expires_at > timezone.now()
                    and row.attempts < 5
                )
                if valid:
                    row.attempts += 1
                    row.save(update_fields=["attempts"])
                    valid = row.customer_id and constant_time_compare(
                        row.code_digest, digest(row, code_form.cleaned_data["code"])
                    )
                if valid:
                    row.used_at = timezone.now()
                    row.save(update_fields=["used_at"])
                    request.session.cycle_key()
                    request.session[key] = {
                        "customer": row.customer_id,
                        "identity": identity_digest(row.customer),
                        "expires": time.time() + 1800,
                    }
                    request.session.pop(challenge_key, None)
                    return redirect("customer-portal", slug=slug)
            code_form.add_error(
                "code", "Código inválido ou expirado. Solicite um novo código."
            )
    return render(
        request,
        "scheduling/customer_portal_login.html",
        {
            "tenant": tenant,
            "form": form,
            "code_form": code_form,
            "pending": pending,
            "notice": notice,
        },
    )
