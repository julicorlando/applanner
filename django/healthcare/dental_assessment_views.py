from io import BytesIO
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django import forms
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Subquery, Prefetch
from accounts.permissions import has_capability
from billing.entitlements import require_module
from core.audit import append_audit
from django.views.decorators.cache import never_cache
from core.crypto import decrypt_text
from scheduling.models import Professional, Appointment
from .patient_scope import patients_for
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
from .models import DentalAssessmentDocument, DentalAssessmentVersion
from .services import clinical_records_for


def _integer(value):
    if not str(value or "").isdigit():
        raise Http404
    return int(value)


def _snapshot_age(payload):
    from datetime import date
    try:
        birth=date.fromisoformat(str(payload.get('patient',{}).get('birth_date','')))
        evaluated=date.fromisoformat(str(payload.get('sections',{}).get('evaluation_date','')))
    except (ValueError,TypeError):return None
    return evaluated.year-birth.year-((evaluated.month,evaluated.day)<(birth.month,birth.day))


def _documents(row, payload=None, historical=None):
    documents=row.documents.filter(removed_at__isnull=True)
    if historical:
        documents=row.documents.filter(pk__in=[d['id'] for d in (payload or {}).get('documents',[]) if isinstance(d,dict) and isinstance(d.get('id'),int)])
    return [
        {
            "id": d.pk,
            "name": decrypt_text(d.filename_encrypted),
            "size": d.size,
            "mime": d.mime_type,
            "kind": d.kind,
            "version": historical,
        }
        for d in documents.order_by("created_at")
    ]


@login_required
@never_cache
def assessment_list(request):
    if request.user.role == "reception":
        return reception_list(request)
    rows = (
        assessments_for(request.user)
        .select_related("customer", "professional__clinical_registration", "professional__user")
        .prefetch_related(Prefetch('versions',queryset=DentalAssessmentVersion.objects.filter(created_by=request.user).only('assessment_id','number','status','created_at').order_by('-number'),to_attr='history_versions'))
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
            patients_for(request.user),
            pk=_integer(request.GET["customer"]),
            tenant_id=request.user.tenant_id,
        )
        rows = rows.filter(customer=patient)
        legacy_entries = legacy_entries.filter(customer=patient)
    return render(
        request,
        "healthcare/dental_assessment_list.html",
        {
            "assessments": Paginator(rows, 50).get_page(request.GET.get("records_page")),
            "legacy_entries": legacy_entries[:200],
            "patient": patient,
            "patient_roster": Paginator(patients_for(request.user).filter(pk=patient.pk).order_by("pk") if patient else patients_for(request.user).order_by("name", "pk"), 50).get_page(request.GET.get("page")),
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
    version_row = None
    if request.GET.get("version"):
        if not row:
            raise Http404
        historical = _integer(request.GET["version"])
        version_row=get_object_or_404(row.versions.only('number','status','created_at'),number=historical)
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
    readonly = bool(row and (row.status == "finalized" or historical or not owner or request.GET.get('view')=='full'))
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
                patients_for(request.user),
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
    if not row and request.method == "GET" and initial.get("customer"):
        from .dentistry import dental_history

        selected_patient = get_object_or_404(
            patients_for(request.user), pk=initial["customer"], tenant_id=request.user.tenant_id
        )
        previous_records = dental_history(
            tenant=request.user.tenant,
            customer=selected_patient,
            user=request.user,
            ip=request.META.get("REMOTE_ADDR", ""),
        )
        if previous_records:
            initial["odontogram_json"] = previous_records[-1]["data"]["odontogram"]
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
            return redirect(reverse("dental-assessments") + "?customer=" + str(saved.customer_id))
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
            "display_version": historical or (row.version if row else None),
            "snapshot_status": version_row.get_status_display() if version_row else (row.get_status_display() if row else ''),
            "snapshot_date": version_row.created_at if version_row else (row.updated_at if row else None),
            "documents": _documents(row,payload,historical) if row else [],
            "payload": payload,
            "patient_initials": "".join(
                word[0]
                for word in payload.get("patient", {}).get("name", "").split()[:2]
            ).upper(),
            "patient_age": _snapshot_age(payload),
            "sections": display_data,
            "text_fields": [form[name] for name in TEXT_FIELDS],
            "body_areas": {},
            "surfaces": sorted(__import__("healthcare.dentistry",fromlist=["SURFACES"]).SURFACES),
            "versions": row.versions.all().order_by("-number") if row and owner else [],
            "professional_profiles": profiles,
            "signature": payload.get("signature") or payload.get("professional", {}),
            "rectifications": clinical_records_for(user=request.user,tenant=request.user.tenant).filter(supersedes_id=row.final_entry_id).order_by('created_at') if row and row.final_entry_id else [],
        },
        status=status,
    )


@login_required
@never_cache
def patient_options(request, pk):
    authorize(request.user)
    patient = get_object_or_404(
        patients_for(request.user), pk=pk, tenant_id=request.user.tenant_id, active=True
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
                "address": patient.full_address or demographics.get("address", ""),
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
    historical=_integer(request.GET['version']) if request.GET.get('version') else None
    document = get_object_or_404(
        DentalAssessmentDocument.objects.select_related(
            "assessment__professional", "assessment__final_entry", "assessment__tenant"
        ),
        pk=pk,
        assessment__in=assessments_for(request.user),
    )
    if historical is None and document.removed_at:raise Http404
    if historical is not None and not document.assessment.versions.filter(number=historical).exists():raise Http404
    raw, filename = read_assessment_document(
        document=document, user=request.user, request=request, version=historical
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


def reception_list(request):
    user=request.user
    if request.method not in {'GET','HEAD'} or not user.is_active or user.is_superuser or not user.tenant_id or user.tenant.archived_at or user.tenant.deleted_at or not has_capability(user,'agenda.manage'):
        raise PermissionDenied
    require_module(user.tenant,'dentistry');require_module(user.tenant,'medical_records')
    from .models import DentalAssessment,MedicalRecordEntry
    from finance.clinic_services import day_bounds
    day_form=forms.DateField(required=False)
    try:day=day_form.clean(request.GET.get('day'))
    except ValidationError:raise Http404
    if day and not 1900 <= day.year <= 2100:raise Http404
    today=timezone.now().astimezone(day_bounds(user.tenant,timezone.localdate())[0].tzinfo).date()
    start,end=day_bounds(user.tenant,day or today)
    visits=Appointment.objects.filter(tenant_id=user.tenant_id,professional__tenant_id=user.tenant_id,
        customer__tenant_id=user.tenant_id,starts_at__gte=start).exclude(status__in=['cancelled','canceled','no_show'])
    if day:visits=visits.filter(starts_at__lte=end)
    if request.GET.get('customer'):
        visits=visits.filter(customer_id=_integer(request.GET['customer']))
    status_rows=DentalAssessment.objects.filter(tenant_id=user.tenant_id,customer_id=OuterRef('customer_id'),professional_id=OuterRef('professional_id')).order_by('-updated_at','-pk')
    entries=MedicalRecordEntry.objects.filter(tenant_id=user.tenant_id,customer_id=OuterRef('customer_id'),professional_id=OuterRef('professional_id'))
    visits=visits.select_related('customer','professional__clinical_registration','professional__user').annotate(record_status=Subquery(status_rows.values('status')[:1]),has_record=Exists(entries),has_patient_assessment=Exists(DentalAssessment.objects.filter(tenant_id=user.tenant_id,customer_id=OuterRef('customer_id'))),has_patient_entry=Exists(MedicalRecordEntry.objects.filter(tenant_id=user.tenant_id,customer_id=OuterRef('customer_id')))).order_by('starts_at','pk')
    append_audit(tenant=user.tenant,user=user,request=request,action='clinical.dental.reception_list',entity_type='Appointment')
    return render(request,'healthcare/dental_assessment_list.html',{'reception_list':True,'scheduled_patients':Paginator(visits,50).get_page(request.GET.get('page')),'selected_day':day,**shell_context(user,request)})
