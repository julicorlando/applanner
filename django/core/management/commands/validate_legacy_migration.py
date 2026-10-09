import hashlib
import json
import os

import pymysql
from django.apps import apps
from django.core.management.base import BaseCommand,CommandError

from core.management.commands.import_legacy_specialized import SPECS


CORE_SPECS=[
    {"table":"tenants","model":"tenants.Tenant"},
    {"table":"users","model":"accounts.User"},
    {"table":"customers","model":"scheduling.Customer"},
    {"table":"professionals","model":"scheduling.Professional"},
    {"table":"services","model":"scheduling.Service"},
    {"table":"appointments","model":"scheduling.Appointment"},
    {"table":"modules","model":"billing.Module"},
    {"table":"plans","model":"billing.Plan"},
    {"table":"subscriptions","model":"billing.Subscription"},
    {"table":"payments","model":"billing.Payment"},
]


def _digest(values):
    h=hashlib.sha256()
    for value in values:
        h.update(("|".join("" if part is None else str(part) for part in value)+"\n").encode())
    return h.hexdigest()


class Command(BaseCommand):
    help="Compara contagens e chaves entre o MySQL legado e o PostgreSQL Django."

    def add_arguments(self,parser):
        parser.add_argument("--strict",action="store_true")
        parser.add_argument("--json",action="store_true")
        parser.add_argument("--only",default="",help="Tabelas separadas por vírgula.")

    def handle(self,*args,**options):
        cfg={
            "host":os.getenv("LEGACY_MYSQL_HOST"),
            "port":int(os.getenv("LEGACY_MYSQL_PORT","3306")),
            "database":os.getenv("LEGACY_MYSQL_DATABASE"),
            "user":os.getenv("LEGACY_MYSQL_USER"),
            "password":os.getenv("LEGACY_MYSQL_PASSWORD"),
            "charset":"utf8mb4",
            "cursorclass":pymysql.cursors.DictCursor,
        }
        missing=[k for k in ("host","database","user","password") if not cfg[k]]
        if missing:
            raise CommandError("Variáveis do MySQL legado ausentes: "+", ".join(missing))
        selected={x.strip() for x in options["only"].split(",") if x.strip()}
        conn=pymysql.connect(**cfg)
        report=[]
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT TABLE_NAME,COLUMN_NAME
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=%s
                """,(cfg["database"],))
                columns={}
                for row in cur.fetchall():
                    columns.setdefault(row["TABLE_NAME"],set()).add(row["COLUMN_NAME"])
            seen=set()
            for spec in CORE_SPECS+SPECS:
                table=spec["table"]
                if table in seen or (selected and table not in selected):
                    continue
                seen.add(table)
                if table not in columns:
                    report.append({"table":table,"status":"missing_legacy"})
                    continue
                model=apps.get_model(spec["model"])
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) total FROM "+table)
                    legacy_count=int(cur.fetchone()["total"])
                django_count=model.objects.count()
                item={
                    "table":table,"model":spec["model"],
                    "legacy_count":legacy_count,"django_count":django_count,
                    "count_match":legacy_count==django_count,
                }
                source_keys=spec.get("keys") or (["id"] if "id" in columns[table] else [])
                if source_keys and all(k in columns[table] for k in source_keys):
                    order=",".join(source_keys)
                    fields=",".join(source_keys)
                    with conn.cursor() as cur:
                        cur.execute("SELECT "+fields+" FROM "+table+" ORDER BY "+order)
                        legacy_keys=[tuple(row[k] for k in source_keys) for row in cur.fetchall()]
                    rename=spec.get("rename",{})
                    target_keys=[]
                    for source in source_keys:
                        target=next((dst for dst,src in rename.items() if src==source),source)
                        target_keys.append(target)
                    field_attnames={f.attname for f in model._meta.concrete_fields}
                    if all(k in field_attnames for k in target_keys):
                        django_keys=list(model.objects.order_by(*target_keys).values_list(*target_keys))
                        item["key_hash_legacy"]=_digest(legacy_keys)
                        item["key_hash_django"]=_digest(django_keys)
                        item["keys_match"]=item["key_hash_legacy"]==item["key_hash_django"]
                item["status"]="ok" if item["count_match"] and item.get("keys_match",True) else "mismatch"
                report.append(item)
        finally:
            conn.close()

        failures=[r for r in report if r.get("status") not in {"ok","missing_legacy"}]
        if options["json"]:
            self.stdout.write(json.dumps(report,ensure_ascii=False,indent=2))
        else:
            for row in report:
                if row["status"]=="missing_legacy":
                    self.stdout.write(row["table"]+": ausente no legado")
                    continue
                marker="OK" if row["status"]=="ok" else "DIVERGENTE"
                keys=""
                if "keys_match" in row:
                    keys=" | chaves="+("OK" if row["keys_match"] else "DIVERGENTE")
                self.stdout.write(
                    row["table"]+": "+marker+" | MySQL="+str(row["legacy_count"])+
                    " | PostgreSQL="+str(row["django_count"])+keys
                )
        if failures and options["strict"]:
            raise CommandError(str(len(failures))+" tabela(s) divergentes.")
        self.stdout.write(self.style.SUCCESS(
            "Validação concluída: "+str(len(report))+" tabelas, "+
            str(len(failures))+" divergência(s)."
        ))
