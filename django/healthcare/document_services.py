import hashlib
import json
from io import BytesIO
from PIL import Image,ImageOps,UnidentifiedImageError
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from core.crypto import encrypt_text,decrypt_text,encrypt_json
from core.audit import append_audit
from billing.entitlements import require_module
from scheduling.models import Professional
from .models import ClinicalRegistration
from .document_models import ProfessionalSignature,ClinicalIssuedDocument
from .services import assert_clinical_access,create_record
from .patient_scope import patients_for


def own_professional(user):
    assert_clinical_access(user)
    if user.is_superuser:raise PermissionDenied
    profile=Professional.objects.filter(tenant_id=user.tenant_id,user=user,active=True).first()
    if not profile:raise PermissionDenied
    require_module(user.tenant,'medical_records')
    return profile


def normalize_signature(upload):
    if upload.size>2*1024*1024:raise ValidationError('Envie PNG ou JPEG com até 2 MB.')
    try:
        with Image.open(upload) as source:
            if source.format not in {'PNG','JPEG'} or source.width*source.height>4000000 or min(source.size)<20:raise ValueError
            image=ImageOps.exif_transpose(source).convert('RGBA');image.thumbnail((1800,600))
            result=BytesIO();image.save(result,'PNG')
            return result.getvalue()
    except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError):
        raise ValidationError('Imagem da assinatura inválida.') from None


@transaction.atomic
def save_signature(user,upload=None,remove=False):
    professional=own_professional(user)
    Professional.objects.select_for_update().get(pk=professional.pk)
    row,_=ProfessionalSignature.objects.get_or_create(professional=professional,defaults={'updated_by':user})
    if not remove and not upload:raise ValidationError('Selecione uma imagem de assinatura.')
    raw=b'' if remove else normalize_signature(upload)
    row.image_encrypted=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).encrypt(raw) if raw else b''
    row.sha256=hashlib.sha256(raw).hexdigest() if raw else '';row.updated_by=user;row.save()
    append_audit(tenant=user.tenant,user=user,action='clinical.signature.removed' if remove else 'clinical.signature.updated',entity_type='ProfessionalSignature',entity_id=row.pk)
    return row


def identity(user):
    professional=own_professional(user)
    registration=ClinicalRegistration.objects.filter(professional=professional).first()
    if not registration:raise ValidationError('Informe seu CRO/UF ou CREFITO no cadastro profissional antes de emitir.')
    registration.full_clean()
    return professional,registration.snapshot()


def _read_image(field):
    if not field:
        return b''
    try:
        with field.open('rb') as stream:
            return stream.read(3*1024*1024)
    except (OSError,ValueError):
        return b''


def clinic_letterhead(tenant):
    """Plain branding values for the PDF; read only validated local files."""
    unit=tenant.units.filter(active=True).order_by('-is_primary','name').first()
    address=''
    if unit:
        street=', '.join(str(v) for v in [unit.address,unit.address_number] if v)
        place=' · '.join(v for v in [street,unit.address_complement,unit.district] if v)
        city=f"{unit.city} ({unit.state})" if unit.city and unit.state else (unit.city or '')
        address=' · '.join(v for v in [place,city] if v)
    return {
        'name':tenant.name,'primary_color':getattr(tenant,'primary_color','') or '',
        'logo':_read_image(unit.logo if unit and unit.logo else None) or _read_image(tenant.logo),
        'city':(unit.city if unit else '') or '',
        'phone':(unit.phone if unit else '') or tenant.phone,
        'whatsapp':(unit.whatsapp if unit else '') or '',
        'instagram':(unit.instagram if unit else '') or getattr(tenant,'public_instagram','') or '',
        'email':(unit.email if unit else '') or tenant.email,
        'address':address,
    }


def patient_header(patient):
    return {'name':patient.name,'cpf':format_cpf(patient.cpf),'phone':patient.phone,'address':patient.full_address,
            'birth_date':patient.birth_date.strftime('%d/%m/%Y') if patient.birth_date else ''}


def format_cpf(value):
    value=''.join(ch for ch in (value or '') if ch.isdigit())
    return f"{value[:3]}.{value[3:6]}.{value[6:9]}-{value[9:]}" if len(value)==11 else value


def verification_url(code,base_url=''):
    from django.urls import reverse
    base=(getattr(settings,'PUBLIC_BASE_URL','') or base_url or 'https://applanner.com.br').rstrip('/')
    return base+reverse('clinical-document-validate',args=[code])


def document_pdf(*,tenant,patient,title,body,professional,signature_image=b'',issued_at=None,kind='declaration',
                 verification_code='',base_url=''):
    from .document_pdf import render_document
    return render_document(kind=kind,title=title,body=body,clinic=clinic_letterhead(tenant),patient=patient_header(patient),
        professional=professional,issued_at=timezone.localtime(issued_at) if issued_at else timezone.localtime(),
        signature_png=signature_image,verification_url=verification_url(verification_code,base_url) if verification_code else '',
        verification_code='-'.join(verification_code[:12].upper()[i:i+4] for i in range(0,12,4)) if verification_code else '')


@transaction.atomic
def finalize_document(*,user,document,body,title,version,confirmed,base_url=''):
    profile,snapshot=identity(user)
    row=ClinicalIssuedDocument.objects.select_for_update().get(pk=document.pk,tenant=user.tenant,professional=profile)
    if row.status=='finalized':return row
    if row.version!=version:raise ValidationError('Outro acesso alterou o rascunho. Atualize a página antes de emitir.')
    if row.kind=='prescription' and snapshot['council']!='CRO':raise ValidationError('O receituário odontológico exige identificação CRO válida.')
    if not confirmed:raise ValidationError('Revise e confirme a autoria antes da emissão.')
    if not patients_for(user).filter(pk=row.customer_id).exists():raise PermissionDenied
    if not body.strip() or len(body)>20000:raise ValidationError('Informe um texto de até 20 mil caracteres.')
    signature=ProfessionalSignature.objects.filter(professional=profile).first()
    if not signature or not signature.image_encrypted:raise ValidationError('Cadastre sua assinatura profissional antes de emitir o documento.')
    raw=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(signature.image_encrypted))
    import secrets
    code=secrets.token_urlsafe(24)
    now=timezone.localtime();pdf=document_pdf(tenant=user.tenant,patient=row.customer,title=title,body=body,professional=snapshot,
        signature_image=raw,issued_at=now,kind=row.kind,verification_code=code,base_url=base_url)
    row.verification_code=code
    row.body_encrypted=encrypt_text(body);row.title=title;row.sha256=hashlib.sha256(pdf).hexdigest()
    row.pdf_encrypted=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).encrypt(pdf)
    row.signature_snapshot_encrypted=encrypt_json({**snapshot,'image_sha256':signature.sha256 if signature else '', 'issued_at':now.isoformat()})
    row.entry=create_record(tenant=user.tenant,customer=row.customer,professional=profile,user=user,title=title,
        content=json.dumps({'document_id':row.pk,'kind':row.kind,'body':body,'sha256':row.sha256,'signature':snapshot},ensure_ascii=False),record_type='observation')
    row.status='finalized';row.finalized_at=now;row.version+=1;row.save()
    append_audit(tenant=user.tenant,user=user,action='clinical.document.finalized',entity_type='ClinicalIssuedDocument',entity_id=row.pk,after={'sha256':row.sha256})
    return row


def text_from_template(template,patient,professional,tenant):
    text=decrypt_text(template.text_encrypted)
    variables={'nome_paciente':patient.name,'cpf_paciente':patient.cpf,'nome_profissional':professional.name,
        'clinica':tenant.name,'data':timezone.localdate().strftime('%d/%m/%Y')}
    for key,value in variables.items():text=text.replace('{'+key+'}',str(value or ''))
    return text


DEFAULT_TITLES={'prescription':'Receituário','certificate':'Atestado','declaration':'Declaração','budget':'Orçamento'}


def brl(value):
    from decimal import Decimal
    text=f"{Decimal(str(value)):,.2f}"
    return 'R$ '+text.replace(',','X').replace('.',',').replace('X','.')


def _today_visit(patient,professional):
    from scheduling.models import Appointment
    from .implementation import tenant_today
    from finance.clinic_services import day_bounds
    start,end=day_bounds(patient.tenant,tenant_today(patient.tenant))
    return Appointment.objects.filter(tenant_id=patient.tenant_id,customer=patient,professional=professional,
        starts_at__gte=start,starts_at__lt=end).exclude(status__in=['cancelled','canceled','no_show']).order_by('starts_at').first()


def latest_budget_lines(user,patient):
    """Most recent proposed/accepted plan authored by this professional, read through the audited ledger."""
    from .models import ClinicalTreatmentPlan
    from .services import read_record
    plan=(ClinicalTreatmentPlan.objects.filter(entry__tenant_id=user.tenant_id,entry__customer=patient,entry__professional__user=user)
          .exclude(status='declined').select_related('entry').order_by('-entry__created_at','-pk').first())
    if not plan:
        return None,[]
    try:
        data=json.loads(read_record(entry=plan.entry,user=user))
    except (PermissionDenied,ValueError,TypeError):
        return None,[]
    return plan,[line for line in data.get('lines',[]) if isinstance(line,dict)]


def default_body(*,kind,user,patient,professional):
    """Editable starting text mirroring the clinic's paper models; the professional reviews before emission."""
    name=patient.name
    if kind=='prescription':
        return ('- Medicamento -------- concentração -------- quantidade\n'
                'Tomar 01 comprimido de 08/08 horas durante 07 dias.\n')
    if kind=='certificate':
        return (f"Atesto para fins trabalhistas que o(a) paciente {name}, esteve sob meus cuidados neste consultório "
                "e deverá se afastar de suas atividades pelo período de 01 (um) dia, por motivo de CID ____.")
    if kind=='declaration':
        visit=_today_visit(patient,professional)
        period=(f"no período de {timezone.localtime(visit.starts_at):%Hh%M} às {timezone.localtime(visit.ends_at):%Hh%M}"
                if visit else "no período de __h às __h")
        return (f"Declaro para os devidos fins que o(a) paciente {name}, esteve sob meus cuidados neste consultório "
                f"{period} em razão de atendimento odontológico.")
    if kind=='budget':
        plan,lines=latest_budget_lines(user,patient)
        rows=['## Procedimentos','']
        if not lines:
            rows+=['Descrição: ','Dentes: ','Valor: ','']
        from decimal import Decimal
        total=Decimal('0')
        for line in lines:
            quantity=int(line.get('quantity') or 1);price=Decimal(str(line.get('price') or '0'));total+=price*quantity
            rows.append('Descrição: '+str(line.get('procedure','')).strip()+(f' (x{quantity})' if quantity>1 else ''))
            if line.get('tooth'):rows.append('Dente: '+str(line['tooth']))
            rows.append('Valor: '+brl(price)+(' (cada)' if quantity>1 else ''))
            if quantity>1:rows.append('Valor total: '+brl(price*quantity))
            rows.append('')
        rows+=['## Formas de Pagamento',f"O investimento para o seu tratamento é de {brl(total) if lines else 'R$ ____'}.",
               'Oferecemos flexibilidade no pagamento:','• À vista','• Parcelado: ____','','Observações: ']
        return '\n'.join(rows)
    return ''
