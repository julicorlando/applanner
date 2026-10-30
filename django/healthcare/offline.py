"""Explicit, encrypted device snapshots and idempotent, permission-checked replay."""
from datetime import timedelta, date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import uuid
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from accounts.models import User
from tenants.models import Tenant
from billing.entitlements import require_module
from core.audit import append_audit
from scheduling.models import Customer, Professional, Appointment, Service
from scheduling.customer_identity import contact_values, identity_matches
from .operation_access import operator, appointments_for, can_read_clinical, can_receive
from .operation_models import OfflineOperation
from .services import clinical_records_for, read_record, create_record


class WalkInForm(forms.Form):
    name = forms.CharField(label='Nome completo', min_length=2, max_length=150)
    phone = forms.CharField(label='Telefone com DDD', max_length=32, required=False)
    email = forms.EmailField(label='E-mail', required=False)
    birth_date = forms.DateField(label='Nascimento', required=False)

    def clean(self):
        data = super().clean()
        if data.get('phone') and data.get('name'):
            try:
                data['name'], data['phone'], data['email'] = contact_values(data['name'], data['phone'], data.get('email'))
            except ValidationError as exc:
                self.add_error('phone', exc)
        data['email'] = (data.get('email') or '').lower()
        if data.get('birth_date') and not date(1900, 1, 1) <= data['birth_date'] <= timezone.localdate():
            self.add_error('birth_date', 'Informe uma data de nascimento válida.')
        return data


def scope(user):
    return f'{user.tenant_id}:{user.pk}'


@require_GET
def shell(request):
    # Public shell only. It contains no identity, CSRF token, patients or clinical content.
    response = render(request, 'healthcare/offline_shell.html')
    response['Cache-Control'] = 'public, max-age=300'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@login_required
@require_GET
@never_cache
@ensure_csrf_cookie
def snapshot(request):
    tenant = operator(request.user)
    user = request.user
    now = timezone.now()
    clinical = can_read_clinical(user)
    appointments = list(appointments_for(user).filter(starts_at__gte=now-timedelta(days=1), starts_at__lte=now+timedelta(days=7))
        .select_related('customer', 'service', 'professional').order_by('starts_at')[:501])
    patients = list(Customer.objects.filter(tenant=tenant, active=True).order_by('-updated_at')[:1001])
    # All records read through the existing audited authorization service. No reception fallback.
    entries = []
    if clinical:
        for row in clinical_records_for(user=user, tenant=tenant).select_related('tenant').order_by('-created_at')[:100]:
            entries.append({'id': row.pk, 'customer': row.customer_id, 'title': row.title, 'at': row.created_at.isoformat(),
                            'content': read_record(entry=row, user=user, ip=request.META.get('REMOTE_ADDR', ''))})
    professionals = Professional.objects.filter(tenant=tenant, active=True)
    if user.role in {'professional', 'healthcare'}:
        professionals = professionals.filter(user=user)
    data = {'schema': 1, 'scope': scope(user), 'company': tenant.name, 'user': user.get_full_name() or user.email,
        'downloaded_at': now.isoformat(), 'expires_at': (now+timedelta(days=7)).isoformat(),
        'permissions': {'clinical': clinical, 'cash': can_receive(user)},
        'limits': {'patients': 1000, 'appointments': 500, 'history': 100},
        'truncated': {'patients': len(patients)>1000, 'appointments': len(appointments)>500},
        'patients': [{'id': x.pk, 'name': x.name, 'phone': x.phone, 'email': x.email,
                      'birth_date': x.birth_date.isoformat() if x.birth_date else ''} for x in patients[:1000]],
        'appointments': [{'id': x.pk, 'customer': x.customer_id, 'customer_name': x.customer.name,
                          'professional': x.professional_id, 'service': x.service_id, 'service_name': x.service.name,
                          'starts_at': x.starts_at.isoformat(), 'status': x.status, 'version': x.updated_at.isoformat(),
                          'price': str(x.service_price_snapshot if x.service_price_snapshot is not None else x.service.price)} for x in appointments[:500]],
        'professionals': list(professionals.values('id', 'name')),
        'services': list(Service.objects.filter(tenant=tenant, active=True).values('id', 'name', 'duration_minutes')),
        'entries': entries}
    append_audit(tenant=tenant, user=user, request=request, action='clinical.offline.snapshot', entity_type='User', entity_id=user.pk,
        after={'patients': min(len(patients),1000), 'appointments': min(len(appointments),500), 'clinical_entries': len(entries)})
    return JsonResponse(data)


def referenced_customer(user, data):
    key = data.get('customer')
    if isinstance(key, str) and key.startswith('local:'):
        try:
            request_id = uuid.UUID(key[6:])
        except ValueError:
            raise ValidationError('Referência local inválida.') from None
        receipt = OfflineOperation.objects.filter(tenant_id=user.tenant_id, user=user, kind='customer', request_id=request_id).first()
        if not receipt:
            raise ValidationError('Sincronize o novo paciente antes deste lançamento.')
        key = receipt.result['customer']
    if not str(key or '').isdigit():
        raise ValidationError('Paciente inválido.')
    return get_object_or_404(Customer, tenant_id=user.tenant_id, pk=key, active=True)


def synced_at(value):
    if not isinstance(value, str):
        raise ValidationError('Data inválida.')
    value = parse_datetime(value)
    if value is None or timezone.is_naive(value) or not timezone.now()-timedelta(days=7) <= value <= timezone.now()+timedelta(minutes=5):
        raise ValidationError('O registro deve ter data e fuso válidos nos últimos 7 dias.')
    return value


@transaction.atomic
def replay(user, operation):
    # Refresh actor inside the transaction; a stored device snapshot grants no server permissions.
    tenant = Tenant.objects.select_for_update().get(pk=user.tenant_id)
    user = User.objects.select_for_update().select_related('tenant').get(pk=user.pk)
    operator(user)
    if user.tenant_id != tenant.pk:
        raise PermissionDenied
    if not isinstance(operation, dict) or set(operation) != {'id', 'scope', 'kind', 'data'} or operation.get('scope') != scope(user):
        raise PermissionDenied('A fila pertence a outra conta ou clínica.')
    try:
        request_id = uuid.UUID(operation['id'])
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Identificador da operação inválido.') from None
    kind = operation['kind']
    data = operation['data']
    if not isinstance(data, dict) or kind not in {'customer', 'appointment', 'checkin', 'evolution', 'cash'}:
        raise ValidationError('Operação não suportada.')
    if kind == 'evolution' and not can_read_clinical(user):
        raise PermissionDenied('Seu vínculo clínico não está ativo.')
    if kind == 'cash' and not can_receive(user):
        raise PermissionDenied('Recebimento não autorizado.')
    fingerprint = hashlib.sha256(json.dumps(operation, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    existing = OfflineOperation.objects.filter(tenant=tenant, user=user, request_id=request_id).first()
    if existing:
        if existing.fingerprint != fingerprint:
            raise ValidationError('Identificador já usado com outro conteúdo. O original foi preservado.')
        return existing.result
    if kind == 'customer':
        form = WalkInForm(data)
        if not form.is_valid():
            raise ValidationError(' '.join(str(x) for errors in form.errors.values() for x in errors))
        fields = form.cleaned_data
        phones, emails = identity_matches(tenant, fields.get('phone') or '', fields.get('email') or '')
        if (fields.get('phone') and phones.exists()) or emails.exists():
            raise ValidationError('Telefone ou e-mail já cadastrado. Revise a fila e selecione o paciente existente; não foi feita mesclagem automática.')
        patient = Customer.objects.create(tenant=tenant, **fields)
        result = {'customer': patient.pk}
    elif kind == 'appointment':
        from scheduling.availability import AvailabilityService
        patient = referenced_customer(user, data)
        professional = get_object_or_404(Professional.objects.select_for_update(), tenant=tenant, pk=data.get('professional'), active=True)
        if user.role in {'professional', 'healthcare'} and professional.user_id != user.pk:
            raise PermissionDenied
        service = get_object_or_404(Service, tenant=tenant, pk=data.get('service'), active=True)
        start = parse_datetime(str(data.get('starts_at', '')))
        if not start or timezone.is_naive(start) or not timezone.now()-timedelta(days=7) <= start <= timezone.now()+timedelta(days=365):
            raise ValidationError('Horário inválido ou fora do intervalo permitido.')
        end = start+timedelta(minutes=service.duration_minutes)
        available = AvailabilityService()
        if not available.professional_offers(tenant, professional.pk, service.pk) or not available.is_available(tenant, professional, start, end, public_rules=False, service=service):
            raise ValidationError('Horário indisponível. Revise o agendamento pendente; nenhum atendimento existente foi alterado.')
        row = Appointment.objects.create(tenant=tenant, unit=professional.unit, customer=patient, professional=professional,
            service=service, service_price_snapshot=service.price, starts_at=start, ends_at=end, source='walk_in', status='pending', created_by=user)
        result = {'appointment': row.pk}
    elif kind in {'checkin', 'cash'}:
        row = get_object_or_404(appointments_for(user).select_for_update(), pk=data.get('appointment'))
        if data.get('version') != row.updated_at.isoformat():
            raise ValidationError('Este atendimento mudou no servidor. Atualize a agenda e revise esta operação.')
        if kind == 'checkin':
            if row.status not in {'pending', 'confirmed'}:
                raise ValidationError('O paciente já chegou ou o atendimento não pode receber chegada.')
            row.checked_in_at = synced_at(data.get('occurred_at'))
            row.status = 'waiting'
            row.save(update_fields=['status', 'checked_in_at', 'updated_at'])
            result = {'appointment': row.pk, 'version': row.updated_at.isoformat()}
        else:
            from billing.models import TenantPaymentTransaction
            from scheduling.settlement import settle_appointment
            if data.get('method') != 'cash':
                raise ValidationError('Offline aceita somente registro de dinheiro recebido. Pix/cartão exigem confirmação online.')
            if not row.professional_id or not row.professional.active:
                raise ValidationError('O atendimento não tem profissional ativo.')
            price = row.service_price_snapshot if row.service_price_snapshot is not None else row.service.price
            try:
                amount = Decimal(str(data.get('amount')))
                if not amount.is_finite() or amount != price or amount <= 0:
                    raise ValueError()
            except (ValueError, InvalidOperation):
                raise ValidationError('Valor recebido difere do valor integral do atendimento. Confira online.') from None
            if TenantPaymentTransaction.objects.filter(tenant=tenant, reference_type='appointment', reference_id=row.pk).exclude(status__in=['failed','cancelled','rejected','expired']).exists():
                raise ValidationError('Existe pagamento eletrônico para este atendimento. Concilie online antes de registrar dinheiro.')
            occurred = synced_at(data.get('occurred_at'))
            if occurred < row.starts_at:
                raise ValidationError('Recebimento/conclusão anterior ao início do atendimento.')
            settlement = settle_appointment(appointment_id=row.pk, professional=row.professional, user=user, attended=True, payment_method='cash')
            result = {'settlement': settlement.pk, 'appointment': row.pk}
    else:
        require_module(tenant, 'medical_records')
        professional = get_object_or_404(Professional.objects.select_related('clinical_registration'), tenant=tenant, user=user, active=True)
        if not hasattr(professional, 'clinical_registration'):
            raise ValidationError('Configure sua habilitação profissional antes de sincronizar a evolução.')
        professional.clinical_registration.full_clean(validate_unique=False)
        patient = referenced_customer(user, data)
        content = data.get('content')
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 20000 or data.get('attestation') is not True:
            raise ValidationError('Informe a evolução (até 20.000 caracteres) e confirme sua autoria.')
        occurred = synced_at(data.get('occurred_at'))
        appointment = None
        if data.get('appointment'):
            appointment = get_object_or_404(appointments_for(user), pk=data['appointment'], customer=patient, professional=professional)
        entry = create_record(tenant=tenant, customer=patient, professional=professional, user=user, appointment=appointment,
            title='Evolução registrada em operação offline', content=json.dumps({'kind': 'offline_evolution', 'schema': 1,
            'occurred_at': occurred.isoformat(), 'received_at': timezone.now().isoformat(), 'content': content.strip()}, ensure_ascii=False))
        result = {'entry': entry.pk}
    receipt = OfflineOperation.objects.create(tenant=tenant, user=user, request_id=request_id, kind=kind, fingerprint=fingerprint, result=result)
    append_audit(tenant=tenant, user=user, action='clinical.offline.synced', entity_type='OfflineOperation', entity_id=receipt.pk, after={'kind': kind, **result})
    return result


@login_required
@require_POST
@never_cache
def synchronize(request):
    operator(request.user)
    if len(request.body) > 100000:
        return JsonResponse({'detail': 'Operação muito extensa.'}, status=413)
    try:
        operation = json.loads(request.body)
        result = replay(request.user, operation)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
        return JsonResponse({'detail': 'Dados inválidos.'}, status=400)
    except ValidationError as exc:
        return JsonResponse({'detail': ' '.join(exc.messages), 'conflict': True}, status=409)
    return JsonResponse({'ok': True, 'result': result})
