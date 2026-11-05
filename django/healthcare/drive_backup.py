"""Private company-authorized PDF backup. No Master clinical download endpoint."""
import base64
import hashlib
import json
import re
from io import BytesIO
from xml.sax.saxutils import escape
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from cryptography.fernet import Fernet
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
from .pdf_styles import clinical_pdf_styles
from pypdf import PdfReader,PdfWriter
from core.crypto import decrypt_text,decrypt_json
from core.audit import append_audit
from .models import MedicalRecordEntry,PhysiotherapyAssessment,DentalAssessment,ClinicalAttachment
from .document_models import ClinicalIssuedDocument
from .drive_models import ClinicalDriveConfiguration,PatientDriveBackup

GOOGLE_TOKEN='https://oauth2.googleapis.com/token'
DRIVE='https://www.googleapis.com/drive/v3'
UPLOAD='https://www.googleapis.com/upload/drive/v3/files'
MAX_BYTES=64*1024*1024


class DriveBackupError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)


def file_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{5,200}',value or ''):raise DriveBackupError('invalid_google_file_id')
    return value


def google(method,url,**kwargs):
    try:response=requests.request(method,url,timeout=60,allow_redirects=False,**kwargs)
    except requests.RequestException as exc:raise DriveBackupError('google_network_unavailable') from exc
    if response.status_code not in {200,201,204,404,409}:raise DriveBackupError(f'google_http_{response.status_code}')
    return response


def access_token(config):
    response=google('POST',GOOGLE_TOKEN,data={'client_id':config.client_id,'client_secret':decrypt_text(config.client_secret_encrypted),
        'refresh_token':decrypt_text(config.refresh_token_encrypted),'grant_type':'refresh_token'})
    try:token=response.json()['access_token']
    except (KeyError,ValueError,TypeError) as exc:raise DriveBackupError('google_reconnect_required') from exc
    return token


def generated_id(token):
    response=google('GET',DRIVE+'/files/generateIds',params={'count':1,'space':'drive','type':'files'},headers={'Authorization':'Bearer '+token})
    try:return file_id(response.json()['ids'][0])
    except (KeyError,ValueError,IndexError) as exc:raise DriveBackupError('google_id_unavailable') from exc


def create_folder(token,name):
    response=google('POST',DRIVE+'/files',params={'fields':'id'},headers={'Authorization':'Bearer '+token},
        json={'name':name[:150],'mimeType':'application/vnd.google-apps.folder'})
    try:return file_id(response.json()['id'])
    except (KeyError,ValueError) as exc:raise DriveBackupError('google_folder_unavailable') from exc


def upload_pdf(config,job,pdf,token):
    headers={'Authorization':'Bearer '+token}
    current=google('GET',DRIVE+'/files/'+file_id(job.file_id),params={'fields':'id,parents,trashed,mimeType','supportsAllDrives':'true'},headers=headers)
    exists=current.status_code==200
    if exists:
        metadata=current.json()
        if metadata.get('trashed') or config.folder_id not in metadata.get('parents',[]) or metadata.get('mimeType')!='application/pdf':
            raise DriveBackupError('google_destination_changed')
    elif current.status_code!=404:raise DriveBackupError('google_file_unavailable')
    metadata={'name':f'prontuario-paciente-{job.customer_id}.pdf','mimeType':'application/pdf'}
    if not exists:metadata.update({'id':job.file_id,'parents':[file_id(config.folder_id)]})
    response=google('PATCH' if exists else 'POST',UPLOAD+('/'+job.file_id if exists else ''),
        params={'uploadType':'resumable','supportsAllDrives':'true','fields':'id'},
        headers={**headers,'X-Upload-Content-Type':'application/pdf','X-Upload-Content-Length':str(len(pdf))},json=metadata)
    location=response.headers.get('Location','')
    from urllib.parse import urlsplit
    target=urlsplit(location)
    if target.scheme!='https' or target.hostname!='www.googleapis.com' or target.port not in {None,443} or target.username or target.password or not target.path.startswith('/upload/drive/v3/files'):
        raise DriveBackupError('invalid_google_upload_session')
    completed=google('PUT',location,headers={**headers,'Content-Type':'application/pdf'},data=pdf)
    if completed.status_code not in {200,201}:raise DriveBackupError('google_upload_not_confirmed')
    if completed.json().get('id')!=job.file_id:raise DriveBackupError('google_file_id_mismatch')


def snapshot(patient):
    """Serialize a coherent source version; do not hash access/export timestamps."""
    tenant=patient.tenant;rows=[];attachments=[];used=0
    def attach(name,raw):
        nonlocal used
        used+=len(raw)
        if used>MAX_BYTES:raise DriveBackupError('patient_pdf_size_limit')
        attachments.append((name,raw))
    for entry in MedicalRecordEntry.objects.filter(tenant=tenant,customer=patient).order_by('created_at','pk'):
        text=decrypt_text(entry.content_encrypted)
        try:data=json.loads(text)
        except (ValueError,TypeError):data={'texto':text}
        if isinstance(data,dict) and isinstance(data.get('signature_png'),str) and data['signature_png'].startswith('data:image/png;base64,'):
            try:attach(f'assinatura-registro-{entry.pk}.png',base64.b64decode(data['signature_png'].split(',',1)[1],validate=True))
            except ValueError:raise DriveBackupError('invalid_archived_signature') from None
        item={'id':entry.pk,'date':entry.created_at.isoformat(),'title':entry.title,'professional':entry.professional_snapshot,
            'supersedes':entry.supersedes_id,'correction':decrypt_text(entry.correction_reason_encrypted) if entry.correction_reason_encrypted else '', 'data':data,'attachments':[]}
        for document in ClinicalAttachment.objects.filter(entry=entry).order_by('pk'):
            raw=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(document.content_encrypted))
            suffix={'application/pdf':'.pdf','image/png':'.png','image/jpeg':'.jpg','application/dicom':'.dcm'}.get(document.mime_type,'.bin')
            attach(f'anexo-{document.pk}{suffix}',raw)
            item['attachments'].append({'id':document.pk,'sha256':hashlib.sha256(raw).hexdigest()})
        rows.append(item)
    for model,label in [(PhysiotherapyAssessment,'Avaliação fisioterapêutica'),(DentalAssessment,'Avaliação odontológica')]:
        for assessment in model.objects.filter(tenant=tenant,customer=patient,status='draft').order_by('pk'):
            rows.append({'id':f'{model.__name__}-{assessment.pk}','title':label+' — RASCUNHO NÃO FINALIZADO','professional_id':assessment.professional_id,
                'version':assessment.version,'data':decrypt_json(assessment.payload_encrypted)})
            for document in assessment.documents.filter(removed_at__isnull=True).order_by('pk'):
                raw=Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(document.content_encrypted))
                attach(f'rascunho-{model.__name__}-{assessment.pk}-anexo-{document.pk}',raw)
                rows[-1].setdefault('attachments',[]).append({'id':document.pk,'sha256':hashlib.sha256(raw).hexdigest()})
    issued=[]
    for doc in ClinicalIssuedDocument.objects.filter(tenant=tenant,customer=patient).order_by('pk'):
        issued.append({'id':doc.pk,'version':doc.version,'status':doc.status,'sha256':doc.sha256,'body':decrypt_text(doc.body_encrypted)})
        if doc.pdf_encrypted:attach(f'documento-emitido-{doc.pk}.pdf',Fernet(settings.FIELD_ENCRYPTION_KEY.encode()).decrypt(bytes(doc.pdf_encrypted)))
    content={'patient':{'id':patient.pk,'name':patient.name,'cpf':patient.cpf,'address':patient.full_address,'birth_date':str(patient.birth_date or '')},
        'clinic':tenant.name,'records':rows,'issued_documents':issued}
    source_hash=hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    return content,attachments,source_hash


def render_backup(content,attachments):
    styles=clinical_pdf_styles();story=[Paragraph('Cópia de segurança do prontuário',styles['Title'])]
    def walk(value,label=''):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'signature_png','signature_image'}:
                    story.append(Paragraph('Assinatura visual preservada nos anexos e documentos originais deste PDF.',styles['Normal']));continue
                walk(item,str(key).replace('_',' ')+': ')
        elif isinstance(value,list):
            for item in value:walk(item,label)
        else:
            for line in (label+str(value if value is not None else '—')).splitlines():
                story.append(Paragraph(escape(line),styles['Normal']))
            story.append(Spacer(1,4))
    walk(content)
    buffer=BytesIO();SimpleDocTemplate(buffer,title='Cópia de segurança do prontuário').build(story)
    writer=PdfWriter();writer.append(PdfReader(BytesIO(buffer.getvalue())))
    for name,raw in attachments:writer.add_attachment(name,raw)
    final=BytesIO();writer.write(final);raw=final.getvalue()
    if len(raw)>MAX_BYTES:raise DriveBackupError('patient_pdf_size_limit')
    return raw


def backup_patient(job_id):
    """Reserve stable remote IDs before uploads; retries update the same file."""
    with transaction.atomic():
        job=PatientDriveBackup.objects.select_for_update().select_related('configuration__tenant','customer').get(pk=job_id)
        config=job.configuration
        if not config.enabled or not config.refresh_token_encrypted or not config.authorized_at or config.generation!=job.generation or job.customer.tenant_id!=config.tenant_id:
            job.status='skipped';job.save(update_fields=['status','updated_at']);return 'skipped'
        if job.status=='processing' and job.started_at and job.started_at>timezone.now()-timezone.timedelta(hours=1):return 'processing'
        job.status='processing';job.started_at=timezone.now();job.save(update_fields=['status','started_at','updated_at'])
    try:
        if config.tenant.archived_at or config.tenant.deleted_at:raise DriveBackupError('clinic_inactive')
        content,attachments,source_hash=snapshot(job.customer)
        token=access_token(config)
        if job.source_sha256==source_hash and job.last_uploaded_at and job.file_id:
            remote=google('GET',DRIVE+'/files/'+file_id(job.file_id),params={'fields':'id,parents,trashed,md5Checksum','supportsAllDrives':'true'},headers={'Authorization':'Bearer '+token})
            if remote.status_code==200:
                meta=remote.json()
                if not meta.get('trashed') and config.folder_id in meta.get('parents',[]) and meta.get('md5Checksum')==job.pdf_md5:
                    job.status='unchanged';job.last_checked_at=timezone.now();job.last_error_code='';job.save();return 'unchanged'
            elif remote.status_code==404:
                job.file_id=generated_id(token);job.save(update_fields=['file_id','updated_at'])
        if not job.file_id:
            job.file_id=generated_id(token);job.save(update_fields=['file_id','updated_at'])
        pdf=render_backup(content,attachments)
        with transaction.atomic():
            config=ClinicalDriveConfiguration.objects.select_for_update().get(pk=config.pk)
            if not config.enabled or config.generation!=job.generation:raise DriveBackupError('backup_configuration_changed')
            upload_pdf(config,job,pdf,token)
            job.source_sha256=source_hash;job.pdf_sha256=hashlib.sha256(pdf).hexdigest();job.pdf_md5=hashlib.md5(pdf,usedforsecurity=False).hexdigest();job.status='success'
            job.last_checked_at=timezone.now();job.last_uploaded_at=job.last_checked_at;job.last_error_code='';job.save()
            append_audit(tenant=config.tenant,user=None,action='clinical.drive.patient.backed_up',entity_type='PatientDriveBackup',entity_id=job.pk,
                after={'patient_id':job.customer_id,'sha256':job.pdf_sha256,'destination_generation':job.generation})
        return 'success'
    except Exception as exc:
        code=exc.code if isinstance(exc,DriveBackupError) else 'clinical_backup_processing_failed'
        PatientDriveBackup.objects.filter(pk=job_id).update(status='failed',last_error_code=code,last_checked_at=timezone.now())
        from communications.models import UserNotification
        from django.urls import reverse
        if config.authorized_by_id and not UserNotification.objects.filter(user_id=config.authorized_by_id,tenant=config.tenant,type='clinical_backup_failed',created_at__gte=timezone.now()-timezone.timedelta(days=1)).exists():
            UserNotification.objects.create(user_id=config.authorized_by_id,tenant=config.tenant,type='clinical_backup_failed',title='Backup clínico requer atenção',
                message='Uma cópia clínica no Google Drive não foi confirmada. Confira a conexão da empresa e o histórico de execução.',severity='danger',action_url=reverse('master-clinical-drive',args=[config.tenant_id]))
        append_audit(tenant=config.tenant,user=None,action='clinical.drive.backup.failed',entity_type='PatientDriveBackup',entity_id=job_id,after={'error_code':code})
        raise DriveBackupError(code) from None
