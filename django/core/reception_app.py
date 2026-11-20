"""ApPlanner Recepção: a desktop-installable app focused on the front desk.

It is the same web system opened in its own window (installable from Edge/Chrome or
through the Windows shortcut installer below). Any user can sign in and keeps exactly
the permissions of their account; the start screen puts the reception's day first.
"""
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from PIL import Image, ImageOps, UnidentifiedImageError

from accounts.permissions import has_capability
from core.audit import append_audit

PANEL_PATH = "/app/recepcao/painel/"
ACTIVE = {"pending", "confirmed", "waiting", "in_progress", "pending_payment"}
STATUS_ORDER = ("waiting", "in_progress", "confirmed", "pending", "pending_payment", "completed", "no_show")
CLINICAL_ROLES = {"professional", "healthcare"}


def _bounds(tenant):
    from finance.clinic_services import day_bounds
    return day_bounds(tenant, timezone.localdate())


def _cash(request, tenant):
    try:
        from finance.clinic_services import access as finance_access
        finance_access(request.user)
    except (PermissionDenied, ImportError):
        return None, False
    from core.unit_scope import selected_unit
    from finance.models import CashSession
    return CashSession.objects.filter(tenant=tenant, unit=selected_unit(request, tenant), status="open").first(), True


def _dental(tenant):
    from billing.entitlements import module_enabled
    from healthcare.navigation import dental_workspace
    return bool(dental_workspace(tenant) and module_enabled(tenant, "dentistry") and module_enabled(tenant, "medical_records"))


@login_required
@never_cache
def panel(request):
    user = request.user
    tenant = user.tenant
    if user.is_superuser or not tenant or tenant.archived_at or tenant.deleted_at:
        return redirect("portal-home")
    from scheduling.models import Appointment
    start, end = _bounds(tenant)
    rows = (Appointment.objects.filter(tenant=tenant, starts_at__gte=start, starts_at__lte=end)
            .exclude(status__in=["cancelled", "canceled"])
            .select_related("customer", "professional", "service").order_by("starts_at", "pk"))
    if user.role in CLINICAL_ROLES:
        rows = rows.filter(professional__user=user)
    if request.method == "POST":
        if request.POST.get("action") != "arrived" or not request.POST.get("appointment", "").isdigit():
            raise PermissionDenied
        if user.role in CLINICAL_ROLES or not has_capability(user, "agenda.manage"):
            raise PermissionDenied("Seu perfil não registra chegadas.")
        with transaction.atomic():
            visit = get_object_or_404(rows.select_for_update(of=("self",)), pk=int(request.POST["appointment"]))
            if visit.status in {"pending", "confirmed"}:
                visit.status = "waiting"
                visit.save(update_fields=["status", "updated_at"])
                append_audit(tenant=tenant, user=user, request=request, action="clinic.patient.arrived",
                             entity_type="Appointment", entity_id=visit.pk)
                messages.success(request, f"Chegada de {visit.customer_display_name} registrada. Paciente aguardando.")
        return redirect(PANEL_PATH)
    visits = list(rows[:200])
    counts = {key: sum(1 for v in visits if v.status == key) for key in STATUS_ORDER}
    cash_session, can_cash = _cash(request, tenant)
    dental = _dental(tenant)
    return render(request, "portal/reception_panel.html", {
        "tenant": tenant, "visits": visits, "counts": counts, "total": len(visits),
        "cash_session": cash_session, "can_cash": can_cash, "dental": dental,
        "can_schedule": has_capability(user, "agenda.manage") and user.role not in CLINICAL_ROLES,
        "can_checkin": has_capability(user, "agenda.manage") and user.role not in CLINICAL_ROLES,
        "today": timezone.localdate(),
    })


@login_required
@never_cache
def install(request):
    return render(request, "portal/reception_install.html", {
        "app_url": request.build_absolute_uri(PANEL_PATH),
    })


@login_required
def windows_installer(request):
    """Small .cmd that creates Desktop and Start menu shortcuts opening the app window in Edge or Chrome."""
    app_url = request.build_absolute_uri(PANEL_PATH)
    icon_url = request.build_absolute_uri(reverse("reception-app-ico"))
    ps = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$appUrl = " + _ps_quote(app_url),
        "$iconUrl = " + _ps_quote(icon_url),
        "$dir = Join-Path $env:LOCALAPPDATA 'ApPlanner'",
        "New-Item -ItemType Directory -Force -Path $dir | Out-Null",
        "$ico = Join-Path $dir 'applanner-recepcao.ico'",
        "try { Invoke-WebRequest -UseBasicParsing -Uri $iconUrl -OutFile $ico } catch { $ico = $null }",
        "$candidates = @(",
        "  \"${env:ProgramFiles(x86)}\\Microsoft\\Edge\\Application\\msedge.exe\",",
        "  \"${env:ProgramFiles}\\Microsoft\\Edge\\Application\\msedge.exe\",",
        "  \"${env:ProgramFiles}\\Google\\Chrome\\Application\\chrome.exe\",",
        "  \"${env:ProgramFiles(x86)}\\Google\\Chrome\\Application\\chrome.exe\",",
        "  \"${env:LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe\")",
        "$exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1",
        "if (-not $exe) { Write-Host 'Instale o Microsoft Edge ou o Google Chrome e rode este instalador de novo.'; exit 1 }",
        "$shell = New-Object -ComObject WScript.Shell",
        "foreach ($place in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {",
        "  $lnk = $shell.CreateShortcut((Join-Path $place 'ApPlanner Recepção.lnk'))",
        "  $lnk.TargetPath = $exe",
        "  $lnk.Arguments = '--app=' + $appUrl + ' --start-maximized'",
        "  $lnk.Description = 'ApPlanner Recepção'",
        "  if ($ico) { $lnk.IconLocation = $ico }",
        "  $lnk.Save()",
        "}",
        "Write-Host 'Pronto! O atalho ApPlanner Recepção está na área de trabalho e no menu Iniciar.'",
        "Start-Process $exe ('--app=' + $appUrl + ' --start-maximized')",
    ])
    import base64
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode()
    script = ("@echo off\r\ntitle Instalar ApPlanner Recepcao\r\necho Instalando o ApPlanner Recepcao neste computador...\r\n"
              f"powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}\r\npause\r\n")
    response = HttpResponse(script, content_type="application/octet-stream")
    response["Content-Disposition"] = 'attachment; filename="Instalar-ApPlanner-Recepcao.cmd"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _logo_image():
    from contenthub.models import PlatformHomepage
    branding = PlatformHomepage.objects.filter(pk=1).first()
    source = branding.favicon if branding and branding.favicon else None
    try:
        if source:
            with source.open("rb") as stream, Image.open(stream) as image:
                return ImageOps.exif_transpose(image).convert("RGBA")
        with Image.open(finders.find("images/applanner-logo.png")) as image:
            return image.convert("RGBA")
    except (OSError, ValueError, UnidentifiedImageError, TypeError):
        raise Http404 from None


@require_GET
def icon_ico(request):
    logo = ImageOps.contain(_logo_image(), (220, 220), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (256, 256), (248, 250, 252, 255))
    canvas.alpha_composite(logo, ((256 - logo.width) // 2, (256 - logo.height) // 2))
    out = BytesIO()
    canvas.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    response = HttpResponse(out.getvalue(), content_type="image/x-icon")
    response["Cache-Control"] = "public, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def manifest(request):
    icons = [{"src": reverse("web-app-icon", args=[size]), "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any"}
             for size in (192, 512)]
    response = JsonResponse({
        "id": PANEL_PATH, "name": "ApPlanner Recepção", "short_name": "Recepção", "lang": "pt-BR",
        "description": "Agenda do dia, chegada de pacientes, prontuários e caixa da clínica.",
        "start_url": PANEL_PATH, "scope": "/", "display": "standalone", "display_override": ["window-controls-overlay", "standalone"],
        "background_color": "#f3f6fb", "theme_color": "#1d4ed8", "icons": icons,
        "shortcuts": [
            {"name": "Agenda", "url": "/app/calendario/"},
            {"name": "Pacientes", "url": "/app/agenda/clientes/"},
            {"name": "Caixa do dia", "url": "/app/clinica/financeiro/"},
            {"name": "Atendimentos de hoje", "url": "/app/hoje/"},
        ],
    }, content_type="application/manifest+json")
    response["Cache-Control"] = "public, max-age=300"
    return response
