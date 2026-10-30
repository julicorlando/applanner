from io import BytesIO
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from core.crypto import decrypt_text
from scheduling.models import Customer, Professional, Appointment
from .dental_assessment_forms import AssessmentForm, TEXT_FIELDS
from .dental_assessment_services import (
    authorize,
    assessments_for,
    read_assessment,
    save_assessment,
    read_assessment_document,
    AssessmentConflict,
)
from .navigation import shell_context
from .models import DentalAssessmentDocument
from .services import clinical_records_for


def _integer(value):
    if not str(value or "").isdigit():
        raise Http404
    return int(value)


def _documents(row):
    return [
        {
            "id": d.pk,
            "name": decrypt_text(d.filename_encrypted),
            "size": d.size,
            "mime": d.mime_type,
            "kind": d.kind,
        }
        for d in row.documents.filter(removed_at__isnull=True).order_by("created_at")
    ]


@login_required
@never_cache
def assessment_list(request):
    rows = (
        assessments_for(request.user)
        .select_related("customer", "professional")
        .order_by("-updated_at", "-pk")
    )
    legacy_entries = (
        clinical_records_for(user=request.user, tenant=request.user.tenant)
        .filter(
            record_type="procedure",
            dental_assessment__isnull=True,
        )
        .select_related("customer", "professional")
        .order_by("-created_at", "-pk")
    )
    patient = None
    if request.GET.get("customer"):
        patient = get_object_or_404(
            Customer,
            pk=_integer(request.GET["customer"]),
            tenant_id=request.user.tenant_id,
        )
        rows = rows.filter(customer=patient)
        legacy_entries = legacy_entries.filter(customer=patient)
    return render(
        request,
        "healthcare/dental_assessment_list.html",
        {
            "assessments": rows[:200],
            "legacy_entries": legacy_entries[:200],
            "patient": patient,
            **shell_context(request.user, request),
        },
    )


@login_required
@never_cache
def assessment_editor(request, pk=None):
    authorize(request.user)
    row = (
        get_object_or_404(
            assessments_for(request.user).select_related(
                "customer", "professional__user", "final_entry"
            ),
            pk=pk,
        )
        if pk
        else None
    )
    historical = None
    if request.GET.get("version"):
        if not row:
            raise Http404
        historical = _integer(request.GET["version"])
        if not row.versions.filter(number=historical).exists():
            raise Http404
    payload = (
        read_assessment(
            assessment=row, user=request.user, request=request, version=historical
        )
        if row
        else {}
    )
    owner = not row or (
        row.created_by_id == request.user.pk
        and row.professional.user_id == request.user.pk
    )
    readonly = bool(row and (row.status == "finalized" or historical or not owner))
    if request.method == "POST" and readonly:
        if (
            owner
            and row.status == "finalized"
            and request.POST.get("action") == "finalize"
            and not historical
        ):
            messages.info(
                request, "Avaliação já finalizada. O registro original foi preservado."
            )
            return redirect("dental-assessment-detail", pk=row.pk)
        raise PermissionDenied(
            "Avaliação finalizada ou compartilhada é somente leitura."
        )
    initial = {
        **payload.get("sections", {}),
        "signature_png": payload.get("signature_png", ""),
    }
    profiles = Professional.objects.filter(
        user=request.user, tenant_id=request.user.tenant_id, active=True
    )
    if row:
        initial.update(
            submission_key=row.submission_key,
            customer=row.customer_id,
            professional=row.professional_id,
            appointment=row.appointment_id,
            version=row.version,
        )
    else:
        initial["professional"] = (
            profiles.order_by("pk").values_list("pk", flat=True).first()
        )
        if request.GET.get("customer"):
            patient = get_object_or_404(
                Customer,
                tenant_id=request.user.tenant_id,
                pk=_integer(request.GET["customer"]),
            )
            initial["customer"] = patient.pk
        if request.GET.get("appointment"):
            appointment = get_object_or_404(
                Appointment,
                tenant_id=request.user.tenant_id,
                professional__user=request.user,
                pk=_integer(request.GET["appointment"]),
            )
            initial.update(
                customer=appointment.customer_id,
                professional=appointment.professional_id,
                appointment=appointment.pk,
            )
    action = request.POST.get("action") if request.method == "POST" else None
    if action and action not in {"draft", "finalize"}:
        raise PermissionDenied
    form = AssessmentForm(
        request.POST if request.method == "POST" else None,
        request.FILES if request.method == "POST" else None,
        user=request.user,
        assessment=row,
        initial=initial,
        finalizing=action == "finalize",
    )
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_assessment(
                form=form,
                user=request.user,
                assessment_id=row.pk if row else None,
                finalize=action == "finalize",
                request=request,
            )
            messages.success(
                request,
                "Avaliação finalizada e vinculada ao prontuário."
                if saved.status == "finalized"
                else "Rascunho salvo com histórico de versões.",
            )
            return redirect("dental-assessment-detail", pk=saved.pk)
        except AssessmentConflict as exc:
            form.add_error(None, exc)
            status = 409
        except ValidationError as exc:
            form.add_error(None, exc)
    if readonly:
        form.fields["professional"].queryset = Professional.objects.filter(
            pk=row.professional_id, tenant_id=request.user.tenant_id
        )
        form.fields["appointment"].queryset = Appointment.objects.filter(
            pk=row.appointment_id, tenant_id=request.user.tenant_id
        )
        for field in form.fields.values():
            field.disabled = True

    display_data = payload.get("sections", {}) if readonly else initial
    # Bound text/JSON values stay in the form after validation errors.
    return render(
        request,
        "healthcare/dental_assessment.html",
        {
            **shell_context(request.user, request),
            "form": form,
            "assessment": row,
            "readonly": readonly,
            "owner": owner,
            "historical": historical,
            "documents": _documents(row) if row else [],
            "payload": payload,
            "patient_initials": "".join(
                word[0]
                for word in payload.get("patient", {}).get("name", "").split()[:2]
            ).upper(),
            "patient_age": (
                timezone.localdate().year
                - row.customer.birth_date.year
                - (
                    (timezone.localdate().month, timezone.localdate().day)
                    < (row.customer.birth_date.month, row.customer.birth_date.day)
                )
            )
            if row and row.customer.birth_date
            else None,
            "sections": display_data,
            "text_fields": [form[name] for name in TEXT_FIELDS],
            "body_areas": {},
            "surfaces": sorted(__import__("healthcare.dentistry",fromlist=["SURFACES"]).SURFACES),
            "versions": row.versions.all().order_by("-number") if row and owner else [],
            "professional_profiles": profiles,
            "signature": payload.get("signature", {}),
        },
        status=status,
    )


@login_required
@never_cache
def patient_options(request, pk):
    authorize(request.user)
    patient = get_object_or_404(
        Customer, pk=pk, tenant_id=request.user.tenant_id, active=True
    )
    professional = request.GET.get("professional", "")
    qs = Appointment.objects.filter(
        tenant_id=request.user.tenant_id,
        customer=patient,
        professional__user=request.user,
        professional__active=True,
    ).exclude(status__in=["cancelled", "canceled"])
    if professional:
        qs = qs.filter(professional_id=_integer(professional))
    previous = assessments_for(request.user).filter(customer=patient).order_by("-updated_at", "-pk").first()
    demographics = read_assessment(assessment=previous, user=request.user, request=request).get("patient", {}) if previous else {}
    today = timezone.localdate()
    birth = patient.birth_date
    return JsonResponse(
        {
            "patient": {
                "name": patient.name,
                "phone": patient.phone,
                "address": demographics.get("address", ""),
                "gender": demographics.get("gender", ""),
                "coverage": demographics.get("coverage", ""),
                "age": today.year
                - birth.year
                - ((today.month, today.day) < (birth.month, birth.day))
                if birth
                else None,
            },
            "appointments": [
                {
                    "id": a.pk,
                    "label": timezone.localtime(a.starts_at).strftime("%d/%m/%Y %H:%M")
                    + " · "
                    + a.service.name,
                }
                for a in qs.select_related("service").order_by("-starts_at")[:200]
            ],
        }
    )


@login_required
@never_cache
def assessment_document(request, pk):
    authorize(request.user)
    document = get_object_or_404(
        DentalAssessmentDocument.objects.select_related(
            "assessment__professional", "assessment__final_entry", "assessment__tenant"
        ),
        pk=pk,
        assessment__in=assessments_for(request.user),
        removed_at__isnull=True,
    )
    raw, filename = read_assessment_document(
        document=document, user=request.user, request=request
    )
    response = FileResponse(
        BytesIO(raw),
        as_attachment=not (request.GET.get("preview") == "1" and document.mime_type in {"image/png", "image/jpeg"}),
        filename=filename,
        content_type=document.mime_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
