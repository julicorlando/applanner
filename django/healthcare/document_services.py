import hashlib
import json
from io import BytesIO
from xml.sax.saxutils import escape
from PIL import Image,ImageOps,UnidentifiedImageError
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image as PDFImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
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


def document_pdf(*,tenant,patient,title,body,professional,signature_image=b'',issued_at=None):
    styles=getSampleStyleSheet();story=[];buffer=BytesIO()
    import re
    color=getattr(tenant,'primary_color','') or ''
    if re.fullmatch(r'#[0-9a-fA-F]{6}',color):
        styles['Title'].textColor=colors.HexColor(color);styles['Heading1'].textColor=colors.HexColor(color)
    # Read local validated branding only; never fetch URLs supplied in document text.
    if tenant.logo:
        try:
            with tenant.logo.open('rb') as stream:
                raw=stream.read(3*1024*1024)
            with Image.open(BytesIO(raw)) as source:
                if source.width*source.height<=4000000:
                    picture=source.convert('RGBA');picture.thumbnail((500,150));out=BytesIO();picture.save(out,'PNG')
                    story.append(PDFImage(BytesIO(out.getvalue()),width=150,height=45,kind='proportional'))
        except (OSError,ValueError,UnidentifiedImageError):pass
    story.append(Paragraph(escape(tenant.name),styles['Title']))
    contacts=' · '.join(v for v in [tenant.document,tenant.phone,tenant.email] if v)
    if contacts:story.append(Paragraph(escape(contacts),styles['Normal']))
    unit=tenant.units.filter(active=True).order_by('-is_primary','name').first()
    if unit:
        address=', '.join(str(v) for v in [unit.address,unit.address_number,unit.district,unit.city,unit.state,unit.postal_code] if v)
        if address:story.append(Paragraph(escape(address),styles['Normal']))
    story.extend([Spacer(1,20),Paragraph(escape(title),styles['Heading1']),Paragraph('Paciente: '+escape(patient.name),styles['Normal'])])
    if patient.cpf:story.append(Paragraph('CPF: '+escape(patient.cpf),styles['Normal']))
    story.extend([Paragraph('Data: '+(issued_at or timezone.now()).strftime('%d/%m/%Y %H:%M'),styles['Normal']),Spacer(1,20)])
    for line in body.splitlines():story.append(Paragraph(escape(line) or ' ',styles['Normal']));story.append(Spacer(1,5))
    story.append(Spacer(1,30))
    if signature_image:story.append(PDFImage(BytesIO(signature_image),width=180,height=60,kind='proportional'))
    text=f"{professional['name']} · {professional['council']} {professional['number']}/{professional['jurisdiction']}"
    story.append(Paragraph(escape(text),styles['Normal']))
    note=styles['Normal'].clone('IntegrityNote');note.fontSize=7;note.textColor=colors.grey
    story.extend([Spacer(1,15),Paragraph('Emitido após confirmação autenticada do profissional. A imagem da assinatura não é assinatura digital certificada.',note)])
    SimpleDocTemplate(buffer,title=title,author=professional['name']).build(story)
    return buffer.getvalue()


@transaction.atomic
def finalize_document(*,user,document,body,title,version,confirmed):
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
    now=timezone.localtime();pdf=document_pdf(tenant=user.tenant,patient=row.customer,title=title,body=body,professional=snapshot,signature_image=raw,issued_at=now)
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
