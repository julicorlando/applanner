import hashlib
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import Backup, BackupVerification, PlatformOperationSettings


def _connection_args():
    cfg=connection.settings_dict
    return {
        "host":cfg.get("HOST") or "localhost",
        "port":str(cfg.get("PORT") or "5432"),
        "name":cfg.get("NAME"),
        "user":cfg.get("USER"),
        "password":cfg.get("PASSWORD") or "",
    }


def _backup_dir():
    path=Path(os.getenv("BACKUP_DIR",str(settings.MEDIA_ROOT/"backups")))
    path.mkdir(parents=True,exist_ok=True)
    return path


def _sha256(path):
    digest=hashlib.sha256()
    with open(path,"rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_database_backup():
    ops,_=PlatformOperationSettings.objects.get_or_create(pk=1)
    now=timezone.now()
    backup=Backup.objects.create(
        type=Backup.Type.DATABASE,
        scope="database",
        status=Backup.Status.RUNNING,
        destination="local-volume",
        started_at=now,
        expires_at=now+timezone.timedelta(days=ops.backup_retention_days),
    )
    path=_backup_dir()/f"applanner-{now:%Y%m%d-%H%M%S}-{backup.pk}.dump"
    cfg=_connection_args()
    env=os.environ.copy()
    env["PGPASSWORD"]=cfg["password"]
    cmd=[
        "pg_dump","--format=custom","--no-owner","--no-privileges",
        "--host",cfg["host"],"--port",cfg["port"],"--username",cfg["user"],
        "--file",str(path),cfg["name"],
    ]
    try:
        result=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=3600)
        if result.returncode!=0:
            raise RuntimeError((result.stderr or "pg_dump falhou")[-1000:])
        backup.status=Backup.Status.COMPLETED
        backup.path=str(path)
        backup.size_bytes=path.stat().st_size
        backup.checksum_sha256=_sha256(path)
        backup.completed_at=timezone.now()
        backup.save(update_fields=["status","path","size_bytes","checksum_sha256","completed_at"])
        return backup
    except Exception as exc:
        backup.status=Backup.Status.FAILED
        backup.error_message=str(exc)[:500]
        backup.completed_at=timezone.now()
        backup.save(update_fields=["status","error_message","completed_at"])
        if path.exists():
            path.unlink(missing_ok=True)
        raise


def verify_database_backup(*,backup,user):
    path=Path(backup.path)
    ok=(
        backup.status==Backup.Status.COMPLETED
        and path.is_file()
        and path.stat().st_size>0
        and _sha256(path)==backup.checksum_sha256
    )
    return BackupVerification.objects.create(
        backup=backup,
        verification_type="integrity",
        status="passed" if ok else "failed",
        checksum_sha256=_sha256(path) if path.is_file() else "",
        details="Checksum e arquivo válidos." if ok else "Arquivo ausente ou checksum divergente.",
        verified_by=user,
        verified_at=timezone.now(),
        completed_at=timezone.now(),
    )


def restore_database_backup(*,backup,target_url,confirm=False):
    if not confirm:
        raise ValueError("Restauração exige confirmação explícita.")
    if backup.status!=Backup.Status.COMPLETED or not backup.path:
        raise ValueError("Backup não está disponível para restauração.")
    path=Path(backup.path)
    if not path.is_file() or _sha256(path)!=backup.checksum_sha256:
        raise ValueError("Integridade do backup inválida.")
    if target_url==os.getenv("DATABASE_URL"):
        raise ValueError("Restauração direta sobre o banco ativo é bloqueada. Use um banco de destino separado.")
    result=subprocess.run(
        ["pg_restore","--clean","--if-exists","--no-owner","--no-privileges","--dbname",target_url,str(path)],
        capture_output=True,text=True,timeout=3600,
    )
    if result.returncode!=0:
        raise RuntimeError((result.stderr or "pg_restore falhou")[-1000:])
    return True


def expire_old_backups():
    now=timezone.now()
    rows=Backup.objects.filter(expires_at__lt=now).exclude(status=Backup.Status.EXPIRED)
    count=0
    for backup in rows:
        if backup.path:
            Path(backup.path).unlink(missing_ok=True)
        backup.status=Backup.Status.EXPIRED
        backup.save(update_fields=["status"])
        count+=1
    return count
