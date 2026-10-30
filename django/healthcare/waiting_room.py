"""Public TV links are revocable capabilities; calls reveal only configured aliases."""
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import re
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, ImageOps, UnidentifiedImageError
from cryptography.fernet import Fernet
from django.conf import settings
from billing.entitlements import require_module, module_enabled
from core.audit import append_audit
from core.crypto import encrypt_text, decrypt_text
from .operation_access import operator, appointments_for, ADMIN
from .operation_models import WaitingRoomDisplay, WaitingRoomCall, WaitingRoomMedia, screen_token


class DisplayForm(forms.ModelForm):
    class Meta:
        model = WaitingRoomDisplay
        fields = ['enabled', 'title', 'voice_enabled', 'show_full_name', 'retention_minutes']
        labels = {'enabled': 'Ativar painel', 'title': 'Título da TV', 'voice_enabled': 'Ativar voz (requer clique na TV)',
                  'show_full_name': 'Exibir nome completo (avalie a privacidade na sala de espera)',
                  'retention_minutes': 'Minutos para apagar as chamadas da TV'}

    def clean_retention_minutes(self):
        value = self.cleaned_data['retention_minutes']
        if not 1 <= value <= 120:
            raise ValidationError('Escolha entre 1 e 120 minutos.')
        return value


class MediaForm(forms.Form):
    title = forms.CharField(label='Título', max_length=100)
    file = forms.FileField(label='Imagem (PNG/JPEG) ou vídeo MP4, até 20 MB')

    def clean_file(self):
        file = self.cleaned_data['file']
        if not 0 < file.size <= 20 * 1024 * 1024:
            raise ValidationError('Arquivo deve ter até 20 MB.')
        data = file.read()
        suffix = Path(file.name).suffix.lower()
        if suffix in {'.png', '.jpg', '.jpeg'}:
            try:
                with Image.open(BytesIO(data)) as source:
                    if source.format not in {'PNG', 'JPEG'} or source.width * source.height > 24000000:
                        raise ValueError()
                    image = ImageOps.exif_transpose(source).convert('RGB')
                    image.thumbnail((1920, 1080))
                    output = BytesIO()
                    image.save(output, format='JPEG', quality=88)
                    return output.getvalue(), 'image/jpeg'
            except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                raise ValidationError('Imagem inválida.') from None
        # Parse bounded ISO BMFF top-level boxes; never trust extension or upload MIME.
        if suffix == '.mp4' and len(data) >= 24 and data[4:8] == b'ftyp':
            offset = 0
            boxes = set()
            while offset < len(data):
                if offset + 8 > len(data):
                    break
                size = int.from_bytes(data[offset:offset+4], 'big')
                kind = data[offset+4:offset+8]
                header = 8
                if size == 1:
                    if offset + 16 > len(data):
                        break
                    size = int.from_bytes(data[offset+8:offset+16], 'big')
                    header = 16
                if size == 0:
                    size = len(data) - offset
                if size < header or offset + size > len(data):
                    break
                boxes.add(kind)
                offset += size
            if offset == len(data) and {b'ftyp', b'moov', b'mdat'} <= boxes:
                return data, 'video/mp4'
        raise ValidationError('Envie uma imagem PNG/JPEG válida ou um vídeo MP4 válido.')


def active_display(slug, token):
    display = get_object_or_404(WaitingRoomDisplay.objects.select_related('tenant'), tenant__slug=slug, token=token, enabled=True)
    if display.tenant.archived_at or display.tenant.deleted_at or not module_enabled(display.tenant, 'waiting-room-tv'):
        raise Http404
    from billing.access import current_subscription, subscription_allows_access
    if settings.SUBSCRIPTION_ACCESS_ENFORCED and not subscription_allows_access(current_subscription(display.tenant)):
        raise Http404
    return display


@login_required
@never_cache
def console(request):
    tenant = operator(request.user)
    require_module(tenant, 'waiting-room-tv')
    display, _ = WaitingRoomDisplay.objects.get_or_create(tenant=tenant)
    admin = request.user.role in ADMIN
    form = DisplayForm(instance=display)
    media_form = MediaForm(auto_id="tv-media-%s")
    if request.method == 'POST':
        if not admin:
            raise PermissionDenied
        action = request.POST.get('action')
        if action == 'settings':
            form = DisplayForm(request.POST, instance=display)
            if form.is_valid():
                form.save()
                append_audit(tenant=tenant, user=request.user, request=request, action='tv.settings.saved', entity_type='WaitingRoomDisplay', entity_id=display.pk)
                return redirect('waiting-room-console')
        elif action == 'rotate':
            display.token = screen_token()
            display.save(update_fields=['token', 'updated_at'])
            append_audit(tenant=tenant, user=request.user, request=request, action='tv.link.revoked', entity_type='WaitingRoomDisplay', entity_id=display.pk)
            return redirect('waiting-room-console')
        elif action == 'upload':
            media_form = MediaForm(request.POST, request.FILES, auto_id="tv-media-%s")
            if media_form.is_valid():
                if display.media.filter(active=True).count() >= 10:
                    media_form.add_error(None, 'Limite de 10 mídias ativas. Desative uma antes de adicionar.')
                else:
                    raw, mime = media_form.cleaned_data['file']
                    row = WaitingRoomMedia(display=display, title=media_form.cleaned_data['title'], mime=mime)
                    encrypted = Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).encrypt(raw)
                    row.file.save(f'{uuid.uuid4().hex}.enc', ContentFile(encrypted), save=True)
                    append_audit(tenant=tenant, user=request.user, request=request, action='tv.media.created', entity_type='WaitingRoomMedia', entity_id=row.pk)
                    return redirect('waiting-room-console')
        elif action == 'disable_media':
            pk = request.POST.get('media', '')
            if not pk.isdigit():
                return HttpResponse('Mídia inválida.', status=400)
            row = get_object_or_404(display.media, pk=pk)
            row.active = False
            row.save(update_fields=['active', 'updated_at'])
            append_audit(tenant=tenant, user=request.user, request=request, action='tv.media.disabled', entity_type='WaitingRoomMedia', entity_id=row.pk)
            return redirect('waiting-room-console')
        else:
            return HttpResponse('Ação inválida.', status=400)
    now = timezone.now()
    rows = appointments_for(request.user).filter(starts_at__gte=now-timedelta(hours=24), starts_at__lte=now+timedelta(hours=24),
        status__in=['pending', 'confirmed', 'waiting', 'in_progress']).select_related('customer', 'professional').order_by('starts_at')[:100]
    return render(request, 'healthcare/waiting_room_console.html', {'display': display, 'form': form, 'media_form': media_form,
        'admin': admin, 'appointments': rows, 'request_id': uuid.uuid4(),
        'tv_url': request.build_absolute_uri(reverse('waiting-room-short', args=[display.token]))})


@login_required
@require_POST
@never_cache
@transaction.atomic
def call_patient(request):
    tenant = operator(request.user)
    require_module(tenant, 'waiting-room-tv')
    display = get_object_or_404(WaitingRoomDisplay.objects.select_for_update(), tenant=tenant, enabled=True)
    pk = request.POST.get('appointment', '')
    if not pk.isdigit():
        return HttpResponse('Atendimento inválido.', status=400)
    appointment = get_object_or_404(appointments_for(request.user).select_for_update(), pk=pk)
    room = request.POST.get('room', '').strip()
    try:
        request_id = uuid.UUID(request.POST.get('request_id', ''))
    except (ValueError, TypeError, AttributeError):
        return HttpResponse('Identificador da chamada inválido.', status=400)
    if not 1 <= len(room) <= 60 or appointment.status not in {'pending', 'confirmed', 'waiting', 'in_progress'}:
        return HttpResponse('Sala ou atendimento inválido.', status=400)
    if abs((appointment.starts_at-timezone.now()).total_seconds()) > 86400:
        return HttpResponse('Chame somente pacientes dos atendimentos atuais.', status=400)
    existing = display.calls.filter(request_id=request_id).first()
    if existing:
        if existing.appointment_id != appointment.pk or existing.room != room or existing.called_by_id != request.user.pk:
            return HttpResponse('Esta chamada já foi usada para outro atendimento.', status=409)
    else:
        name = appointment.customer.name.split()
        label = appointment.customer.name if display.show_full_name else name[0] + (f' {name[-1][0]}.' if len(name) > 1 else '')
        row = WaitingRoomCall.objects.create(display=display, appointment=appointment, called_by=request.user,
            label_encrypted=encrypt_text(label), room=room, request_id=request_id,
            expires_at=timezone.now()+timedelta(minutes=display.retention_minutes))
        append_audit(tenant=tenant, user=request.user, request=request, action='tv.patient.called', entity_type='WaitingRoomCall', entity_id=row.pk,
            after={'appointment_id': appointment.pk})
    messages.success(request, 'Paciente chamado na TV.')
    return redirect('waiting-room-console')


@require_GET
@never_cache
def screen(request, slug, token):
    display = active_display(slug, token)
    public_link = ''
    if display.tenant.public_enabled and display.tenant.public_short_code:
        public_link = request.build_absolute_uri(reverse('tenant-short-link', args=[display.tenant.public_short_code]))
    response = render(request, 'healthcare/waiting_room_screen.html', {'display': display, 'public_link': public_link})
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


@require_GET
@never_cache
def feed(request, slug, token):
    display = active_display(slug, token)
    rows = display.calls.filter(expires_at__gt=timezone.now()).order_by('-created_at')[:6]
    data = {'title': display.title, 'voice': display.voice_enabled,
        'calls': [{'id': row.pk, 'name': decrypt_text(row.label_encrypted), 'room': row.room,
                   'at': row.created_at.isoformat()} for row in rows],
        'media': [{'url': reverse('waiting-room-media', args=[slug, token, row.pk]), 'mime': row.mime, 'title': row.title}
                  for row in display.media.filter(active=True).order_by('pk')]}
    response = JsonResponse(data)
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


@require_GET
@never_cache
def media(request, slug, token, pk):
    display = active_display(slug, token)
    row = get_object_or_404(display.media, pk=pk, active=True)
    with row.file.open('rb') as stream:
        raw = Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(stream.read())
    size = len(raw)
    header = request.headers.get('Range', '')
    if header:
        match = re.fullmatch(r'bytes=(\d+)-(\d*)', header)
        if not match:
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        start = int(match[1]); end = min(int(match[2]) if match[2] else size-1, size-1)
        if not 0 <= start <= end:
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        response = HttpResponse(raw[start:end+1], status=206, content_type=row.mime)
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    else:
        response = FileResponse(BytesIO(raw), content_type=row.mime)
    response['Accept-Ranges'] = 'bytes'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_GET
@never_cache
def short_link(request, token):
    display = get_object_or_404(WaitingRoomDisplay.objects.select_related('tenant'), token=token)
    active_display(display.tenant.slug, token)
    response = redirect('waiting-room-screen', slug=display.tenant.slug, token=token)
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response
