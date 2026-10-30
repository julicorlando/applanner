from io import BytesIO
from uuid import uuid4
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from PIL import Image, ImageOps
from accounts.permissions import has_capability
from scheduling.models import Appointment, AppointmentWorkNote, Professional
from .audit import append_audit


class WorkNoteForm(forms.Form):
    cut_style = forms.CharField(max_length=200, required=False, label="Corte, máquina e altura do degradê")
    beard = forms.CharField(max_length=200, required=False, label="Barba e acabamento")
    color_formula = forms.CharField(max_length=1000, required=False, label="Fórmula de coloração e proporções", widget=forms.Textarea(attrs={"rows":2}))
    products = forms.CharField(max_length=500, required=False, label="Produtos e quantidades utilizadas")
    processing_minutes = forms.IntegerField(min_value=0, max_value=600, required=False, label="Tempo de aplicação / pausa (minutos)")
    preferences = forms.CharField(max_length=500, required=False, label="Preferências e cuidados informados pelo cliente")
    result = forms.CharField(max_length=1000, required=False, label="Resultado e recomendações", widget=forms.Textarea(attrs={"rows":2}))
    text = forms.CharField(
        max_length=4000,
        label="Anotação técnica",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    photo = forms.ImageField(required=False, label="Foto do atendimento (até 5 MB)")
    photo_consent = forms.BooleanField(
        required=False, label="Tenho autorização do cliente para registrar esta foto"
    )

    def clean(self):
        data = super().clean()
        photo = data.get("photo")
        if photo and (
            photo.size > 5 * 1024 * 1024
            or photo.image.width * photo.image.height > 20000000
            or not data.get("photo_consent")
        ):
            raise ValidationError("A foto exige autorização e deve ter até 5 MB.")
        return data


def authorized_appointment(request, pk):
    user = request.user
    if not user.is_authenticated:
        raise PermissionDenied
    if user.role == "professional":
        professional = get_object_or_404(
            Professional, user=user, tenant_id=user.tenant_id, active=True
        )
        return get_object_or_404(
            Appointment, pk=pk, tenant=professional.tenant, professional=professional
        )
    if (
        not user.tenant_id
        or user.role == "reception"
        or not has_capability(user, "agenda.manage")
    ):
        raise PermissionDenied
    return get_object_or_404(Appointment, pk=pk, tenant_id=user.tenant_id)


@login_required
@never_cache
def notes(request, pk):
    appointment = authorized_appointment(request, pk)
    initial={}
    if request.method=="GET" and request.GET.get('repeat'):
        previous=get_object_or_404(AppointmentWorkNote, pk=request.GET['repeat'], tenant=appointment.tenant,
            appointment__customer=appointment.customer)
        authorized_appointment(request, previous.appointment_id)
        initial=previous.technical
        initial['text']='Referência da ficha #'+str(previous.pk)+'. Confira os dados antes de salvar.'
    form = WorkNoteForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        row = AppointmentWorkNote(
            tenant=appointment.tenant,
            appointment=appointment,
            user=request.user,
            text=data["text"],
            photo_consent=data["photo_consent"],
        )
        from core.crypto import encrypt_json
        row.technical_encrypted=encrypt_json({key:data.get(key) for key in [
            'cut_style','beard','color_formula','products','processing_minutes','preferences','result']})
        if data["photo"]:
            with Image.open(data["photo"]) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.save(output, format="JPEG", quality=88)
            row.photo.save(
                f"{uuid4().hex}.jpg", ContentFile(output.getvalue()), save=False
            )
        row.save()
        append_audit(
            tenant=appointment.tenant,
            user=request.user,
            request=request,
            action="WORK_NOTE_CREATED",
            entity_type="AppointmentWorkNote",
            entity_id=row.pk,
            after={"appointment": appointment.pk, "has_photo": bool(row.photo)},
        )
        messages.success(request, "Ficha técnica registrada com acesso restrito.")
        return redirect("appointment-work-notes", pk=appointment.pk)
    history = Appointment.objects.filter(
        tenant=appointment.tenant, customer=appointment.customer
    )
    if request.user.role == "professional":
        history = history.filter(professional=appointment.professional)
    return render(
        request,
        "portal/work_notes.html",
        {
            "appointment": appointment,
            "form": form,
            "notes": AppointmentWorkNote.objects.filter(
                tenant=appointment.tenant, appointment__in=history
            )
            .select_related("user", "appointment__service")
            .order_by("-created_at")[:100],
        },
    )


@login_required
@never_cache
def photo(request, pk):
    row = get_object_or_404(AppointmentWorkNote, pk=pk)
    authorized_appointment(request, row.appointment_id)
    if not row.photo:
        raise PermissionDenied
    response = FileResponse(row.photo.open("rb"), content_type="image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    return response


class PrivateMediaGuard:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/media/private/"):
            return HttpResponseNotFound()
        return self.get_response(request)
