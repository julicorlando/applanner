import base64
import hashlib
from cryptography.fernet import InvalidToken
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from accounts.login_limits import attempt_budget, limited_response
from core.crypto import decrypt_text
from core.customer_import_views import require_master
from .forms import ClientForm, ChargeForm, PasswordForm, SettlementForm
from .models import Client, Charge, Delivery, Invitation
from .services import audit, invite, save_charge, save_client, settle


@login_required
@never_cache
@require_http_methods(["GET"])
def clients(request):
    require_master(request)
    rows = Client.objects.select_related("user").order_by("name")
    q = request.GET.get("q", "").strip()[:100]
    if q:
        from django.db.models import Q

        rows = rows.filter(
            Q(name__icontains=q)
            | Q(company_name__icontains=q)
            | Q(user__email__icontains=q)
        )
    from django.core.paginator import Paginator

    return render(
        request,
        "development/clients.html",
        {"page": Paginator(rows, 30).get_page(request.GET.get("page")), "q": q},
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def client_form(request, pk=None):
    require_master(request)
    row = (
        get_object_or_404(Client.objects.select_related("user"), pk=pk) if pk else None
    )
    form = ClientForm(request.POST if request.method == "POST" else None, instance=row)
    if request.method == "POST" and form.is_valid():
        try:
            row = save_client(form, request)
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            form.add_error(None, "E-mail ou CPF/CNPJ já cadastrado. Confira os dados.")
        else:
            messages.success(
                request,
                "Cliente salvo. No primeiro cadastro, o convite de senha entra na fila de e-mail e WhatsApp.",
            )
            return redirect("development-client", pk=row.pk)
    return render(
        request,
        "development/form.html",
        {
            "form": form,
            "title": "Editar cliente" if row else "Novo cliente de desenvolvimento",
            "multipart": False,
        },
    )


@login_required
@never_cache
@require_http_methods(["GET"])
def client_detail(request, pk):
    require_master(request)
    row = get_object_or_404(Client.objects.select_related("user"), pk=pk)
    return render(
        request,
        "development/client.html",
        {
            "customer": row,
            "charges": row.charges.order_by("-due_date", "-pk")[:100],
            "deliveries": row.deliveries.order_by("-pk")[:30],
        },
    )


@login_required
@require_POST
def resend_invite(request, pk):
    require_master(request)
    row = get_object_or_404(Client, pk=pk)
    try:
        invite(row)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        audit(request, "invitation-reissued", row)
        messages.success(
            request, "Novo convite na fila. O convite anterior foi invalidado."
        )
    return redirect("development-client", pk=pk)


@login_required
@require_POST
def retry_delivery(request, pk):
    require_master(request)
    row = get_object_or_404(Delivery, pk=pk, channel="whatsapp")
    with transaction.atomic():
        Client.objects.select_for_update().get(pk=row.client_id)
        row = Delivery.objects.select_for_update().get(pk=pk)
        if row.status == "failed" and row.payload_encrypted:
            row.status, row.attempts, row.next_attempt_at = "pending", 0, timezone.now()
            row.save(
                update_fields=["status", "attempts", "next_attempt_at", "updated_at"]
            )
            audit(request, "delivery-retry", row)
            messages.success(
                request,
                "Envio recolocado na fila. A situação da cobrança será conferida antes de enviar.",
            )
    return redirect("development-client", pk=row.client_id)


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def charge_form(request, client_pk, pk=None):
    require_master(request)
    customer = get_object_or_404(Client, pk=client_pk)
    row = (
        get_object_or_404(Charge, pk=pk, client=customer, status="open") if pk else None
    )
    form = ChargeForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        instance=row,
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_charge(form, customer, request)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                "Cobrança salva. Os lembretes seguem os prazos configurados e param após a baixa.",
            )
            return redirect("development-client", pk=customer.pk)
    return render(
        request,
        "development/form.html",
        {"form": form, "title": f"Cobrança · {customer.name}", "multipart": True},
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def settlement(request, pk, action):
    require_master(request)
    if action not in {"paid", "cancelled"}:
        raise PermissionDenied
    row = get_object_or_404(Charge.objects.select_related("client"), pk=pk)
    form = SettlementForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            settle(row.pk, action, form.cleaned_data["note"], request)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Baixa registrada e lembretes interrompidos.")
            return redirect("development-client", pk=row.client_id)
    return render(
        request,
        "development/form.html",
        {
            "form": form,
            "title": (
                "Confirmar pagamento" if action == "paid" else "Cancelar cobrança"
            )
            + f" · R$ {row.amount}",
            "warning": "Confira o recebimento no banco antes de dar baixa. Esta ação fica registrada na auditoria.",
        },
    )


@never_cache
@require_http_methods(["GET", "POST"])
def activate(request, token):
    row = (
        Invitation.objects.select_related("client__user")
        .filter(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
            client__active=True,
            client__user__is_active=True,
            client__user__deleted_at__isnull=True,
        )
        .first()
    )
    if not row or row.client.user.has_usable_password():
        return render(
            request, "development/activate.html", {"invalid": True}, status=400
        )
    form = PasswordForm(
        request.POST if request.method == "POST" else None, user=row.client.user
    )
    if request.method == "POST":
        _, wait = attempt_budget(request, "development-activate", row.pk)
        if wait:
            return limited_response(wait)
        if form.is_valid():
            with transaction.atomic():
                customer = Client.objects.select_for_update().get(pk=row.client_id)
                locked = Invitation.objects.select_for_update().get(pk=row.pk)
                if (
                    locked.used_at
                    or locked.expires_at <= timezone.now()
                    or not customer.active
                    or customer.user.has_usable_password()
                    or not customer.user.is_active
                    or customer.user.deleted_at
                ):
                    return render(
                        request,
                        "development/activate.html",
                        {"invalid": True},
                        status=400,
                    )
                user = customer.user
                user.set_password(form.cleaned_data["password"])
                user.password_changed_at = timezone.now()
                user.session_version += 1
                user.save(
                    update_fields=["password", "password_changed_at", "session_version"]
                )
                customer.invitations.filter(used_at__isnull=True).update(
                    used_at=timezone.now()
                )
                customer.deliveries.filter(
                    invitation__isnull=False, status__in=["pending", "failed"]
                ).update(status="cancelled", payload_encrypted="")
            messages.success(
                request,
                "Senha criada. Entre com seu e-mail para acessar seus pagamentos.",
            )
            return redirect("accounts:login")
    response = render(request, "development/activate.html", {"form": form})
    response["Referrer-Policy"] = "no-referrer"
    return response


def customer_for(request):
    if (
        request.user.role != "development-client"
        or request.user.tenant_id
        or request.user.is_staff
        or request.user.is_superuser
    ):
        raise PermissionDenied
    return get_object_or_404(
        Client,
        user=request.user,
        active=True,
        user__is_active=True,
        user__deleted_at__isnull=True,
    )


@login_required
@never_cache
@require_http_methods(["GET"])
def portal(request):
    customer = customer_for(request)
    from django.core.paginator import Paginator

    page = Paginator(customer.charges.order_by("due_date", "pk"), 30).get_page(
        request.GET.get("page")
    )
    return render(
        request, "development/payments.html", {"customer": customer, "page": page}
    )


def authorized_charge(request, pk):
    if request.user.is_superuser:
        require_master(request)
        return get_object_or_404(Charge.objects.select_related("bank", "client"), pk=pk)
    return get_object_or_404(
        Charge.objects.select_related("bank", "client"),
        pk=pk,
        client=customer_for(request),
    )


@login_required
@never_cache
@require_http_methods(["GET"])
def charge_detail(request, pk):
    row = authorized_charge(request, pk)
    bank = row.bank
    account = None
    if (
        bank
        and bank.status == "active"
        and not bank.deleted_at
        and row.status == "open"
    ):
        try:
            account = {
                "name": bank.bank_name,
                "holder": bank.holder_name,
                "agency": decrypt_text(bank.agency_encrypted),
                "agency_digit": bank.agency_digit,
                "account": decrypt_text(bank.account_encrypted),
                "account_digit": bank.account_digit,
                "pix": decrypt_text(bank.pix_key_encrypted)
                if bank.pix_key_encrypted
                else "",
            }
        except (ValueError, TypeError, InvalidToken):
            account = None
    return render(request, "development/charge.html", {"charge": row, "bank": account})


@login_required
@never_cache
@require_http_methods(["GET"])
def boleto(request, pk):
    row = authorized_charge(request, pk)
    if not row.boleto_encrypted or row.status == "cancelled":
        from django.http import Http404

        raise Http404
    data = base64.b64decode(decrypt_text(row.boleto_encrypted), validate=True)
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="boleto-{row.pk}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    return response
