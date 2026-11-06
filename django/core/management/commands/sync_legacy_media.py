import hashlib, os, shutil
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

class Command(BaseCommand):
    help="Copia mídia do PHP para MEDIA_ROOT e verifica SHA-256."
    def add_arguments(self,parser):
        parser.add_argument("--source",default=os.getenv("LEGACY_MEDIA_ROOT",""))
        parser.add_argument("--dry-run",action="store_true")
        parser.add_argument("--overwrite",action="store_true")
    def handle(self,*args,**options):
        source=Path(options["source"]).expanduser()
        if not source.is_dir(): raise CommandError("Informe --source ou LEGACY_MEDIA_ROOT válido.")
        target=Path(settings.MEDIA_ROOT); copied=verified=skipped=0
        for src in source.rglob("*"):
            if not src.is_file(): continue
            rel=src.relative_to(source); dst=target/rel
            if dst.exists() and not options["overwrite"]:
                if self._sha(src)==self._sha(dst): verified+=1
                else: skipped+=1; self.stderr.write(f"divergente: {rel}")
                continue
            if options["dry_run"]: copied+=1; self.stdout.write(f"copiar: {rel}"); continue
            dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
            if self._sha(src)!=self._sha(dst): raise CommandError(f"Checksum falhou: {rel}")
            copied+=1
        self.stdout.write(self.style.SUCCESS(f"Mídia: {copied} copiadas, {verified} verificadas, {skipped} divergentes."))
    def _sha(self,path):
        h=hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda:fh.read(1024*1024),b""): h.update(chunk)
        return h.hexdigest()
