import hashlib, os
import pymysql
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from core.management.commands.import_legacy_specialized import SPECS

CORE=[("tenants","tenants.Tenant"),("users","accounts.User"),("customers","scheduling.Customer"),
("professionals","scheduling.Professional"),("services","scheduling.Service"),
("appointments","scheduling.Appointment"),("modules","billing.Module"),("plans","billing.Plan"),
("subscriptions","billing.Subscription"),("payments","billing.Payment")]

class Command(BaseCommand):
    help="Compara contagens e IDs entre MySQL legado e PostgreSQL."
    def add_arguments(self,parser):
        parser.add_argument("--strict",action="store_true")
        parser.add_argument("--only",default="")
    def handle(self,*args,**options):
        cfg={"host":os.getenv("LEGACY_MYSQL_HOST"),"port":int(os.getenv("LEGACY_MYSQL_PORT","3306")),
             "database":os.getenv("LEGACY_MYSQL_DATABASE"),"user":os.getenv("LEGACY_MYSQL_USER"),
             "password":os.getenv("LEGACY_MYSQL_PASSWORD"),"charset":"utf8mb4","cursorclass":pymysql.cursors.DictCursor}
        missing=[k for k in ("host","database","user","password") if not cfg[k]]
        if missing: raise CommandError("Variáveis legadas ausentes: "+", ".join(missing))
        selected={x.strip() for x in options["only"].split(",") if x.strip()}
        specs=CORE+[(s["table"],s["model"]) for s in SPECS]
        seen=set(); failures=[]; conn=pymysql.connect(**cfg)
        try:
            for table,label in specs:
                if table in seen or (selected and table not in selected): continue
                seen.add(table)
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) n FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",(cfg["database"],table))
                    if not cur.fetchone()["n"]:
                        self.stdout.write(f"{table}: ausente no legado; ignorando"); continue
                    cur.execute(f"SELECT COUNT(*) n FROM `{table}`"); legacy=int(cur.fetchone()["n"])
                    cur.execute("SELECT COUNT(*) n FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME='id'",(cfg["database"],table))
                    has_id=bool(cur.fetchone()["n"]); legacy_hash=None
                    if has_id:
                        cur.execute(f"SELECT id FROM `{table}` ORDER BY id")
                        legacy_hash=self._hash([r["id"] for r in cur.fetchall()])
                model=apps.get_model(label); target=model.objects.count(); target_hash=None
                if model._meta.pk.get_internal_type() in {"AutoField","BigAutoField","IntegerField","BigIntegerField","PositiveIntegerField","PositiveBigIntegerField","SmallIntegerField"}:
                    target_hash=self._hash(model.objects.order_by("pk").values_list("pk",flat=True))
                ok=legacy==target and (legacy_hash is None or target_hash is None or legacy_hash==target_hash)
                self.stdout.write(f"{table}: legado={legacy} django={target} {'OK' if ok else 'DIVERGENTE'}")
                if not ok: failures.append(table)
        finally: conn.close()
        if failures:
            msg="Divergências: "+", ".join(failures)
            if options["strict"]: raise CommandError(msg)
            self.stderr.write(self.style.WARNING(msg))
        else: self.stdout.write(self.style.SUCCESS("Paridade de contagens/IDs aprovada."))
    def _hash(self,values):
        h=hashlib.sha256()
        for value in values: h.update((str(value)+"\n").encode())
        return h.hexdigest()
