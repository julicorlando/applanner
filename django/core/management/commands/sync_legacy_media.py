import hashlib
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand,CommandError


def _sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


class Command(BaseCommand):
    help="Sincroniza arquivos de mídia do legado para MEDIA_ROOT preservando caminhos."

    def add_arguments(self,parser):
        parser.add_argument("--source",required=True)
        parser.add_argument("--dry-run",action="store_true")
        parser.add_argument("--overwrite",action="store_true")
        parser.add_argument("--verify",action="store_true")

    def handle(self,*args,**options):
        source=Path(options["source"]).expanduser().resolve()
        target=Path(settings.MEDIA_ROOT).resolve()
        if not source.is_dir():
            raise CommandError("Origem não encontrada: "+str(source))
        target.mkdir(parents=True,exist_ok=True)
        copied=skipped=verified=0
        for src in source.rglob("*"):
            if not src.is_file():
                continue
            rel=src.relative_to(source)
            dst=target/rel
            if dst.exists() and not options["overwrite"]:
                if options["verify"] and src.stat().st_size==dst.stat().st_size and _sha256(src)==_sha256(dst):
                    verified+=1
                skipped+=1
                continue
            if options["dry_run"]:
                self.stdout.write("copiar: "+str(rel))
                copied+=1
                continue
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dst)
            copied+=1
            if options["verify"]:
                if src.stat().st_size!=dst.stat().st_size or _sha256(src)!=_sha256(dst):
                    raise CommandError("Checksum divergente após cópia: "+str(rel))
                verified+=1
        self.stdout.write(self.style.SUCCESS(
            "Mídia: "+str(copied)+" copiado(s), "+str(skipped)+
            " ignorado(s), "+str(verified)+" verificado(s)."
        ))
