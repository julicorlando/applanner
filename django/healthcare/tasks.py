"""Celery autodiscovery entry point for clinical jobs."""
from celery import shared_task

from .drive_tasks import queue_daily_clinical_drive_backups,send_patient_drive_backup


@shared_task
def finalize_expired_dental_evolutions():
    """Rascunhos de evolução odontológica com mais de DENTAL_EVOLUTION_DRAFT_HOURS viram FINALIZADO."""
    from .evolution_services import finalize_expired
    return finalize_expired()


__all__=["queue_daily_clinical_drive_backups","send_patient_drive_backup","finalize_expired_dental_evolutions"]
