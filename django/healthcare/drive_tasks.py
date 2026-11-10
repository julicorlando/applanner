from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from communications.birthdays import local_now
from .drive_models import ClinicalDriveConfiguration,PatientDriveBackup
from .models import MedicalRecordEntry,PhysiotherapyAssessment,DentalAssessment
from .document_models import ClinicalIssuedDocument
from .drive_backup import backup_patient,DriveBackupError


@shared_task(bind=True,max_retries=3)
def send_patient_drive_backup(self,job_id):
    try:return backup_patient(job_id)
    except DriveBackupError as exc:
        if self.request.retries>=self.max_retries:return 'failed'
        raise self.retry(exc=exc,countdown=60*(self.request.retries+1))


@transaction.atomic
def enqueue_company(configuration_id,force=False):
    config=ClinicalDriveConfiguration.objects.select_for_update().select_related('tenant').get(pk=configuration_id)
    if not config.enabled or not config.authorized_at or not config.refresh_token_encrypted or not config.folder_id:
        return 0
    if config.tenant.archived_at or config.tenant.deleted_at:return 0
    now=local_now(config.tenant)
    if not force and now.hour<config.hour:return 0
    if force or config.last_queued_day!=now.date():
        ids=set()
        for model in (MedicalRecordEntry,PhysiotherapyAssessment,DentalAssessment,ClinicalIssuedDocument):
            ids.update(model.objects.filter(tenant=config.tenant).values_list('customer_id',flat=True))
        for pk in sorted(ids):
            job,_=PatientDriveBackup.objects.get_or_create(configuration=config,customer_id=pk,generation=config.generation)
            if job.status=='processing' and job.started_at and job.started_at>timezone.now()-timezone.timedelta(hours=1):continue
            job.status='pending';job.save(update_fields=['status','updated_at'])
        config.last_queued_day=now.date();config.save(update_fields=['last_queued_day','updated_at'])
    ids=list(config.backups.filter(generation=config.generation).filter(
        Q(status__in=['pending','failed'])|Q(status='processing',started_at__lt=timezone.now()-timezone.timedelta(hours=1))).values_list('pk',flat=True))
    for pk in ids:
        transaction.on_commit(lambda pk=pk:send_patient_drive_backup.delay(pk))
    return len(ids)


@shared_task
def queue_daily_clinical_drive_backups():
    total=0
    for pk in ClinicalDriveConfiguration.objects.filter(enabled=True).values_list('pk',flat=True):
        total+=enqueue_company(pk)
    return total
