import hashlib
import os

import pymysql
from django.apps import apps
from django.core.management.base import BaseCommand,CommandError

from core.management.commands.import_legacy_specialized import SPECS


DIRECT=[
    ("tenants","tenants.Tenant"),
    ("units","tenants.Unit"),
    ("users","accounts.User"),
    ("email_verification_tokens","accounts.EmailVerificationToken"),
    ("password_reset_tokens","accounts.PasswordResetToken"),
    ("roles","accounts.PlatformRole"),
    ("permissions","accounts.Capability"),
    ("role_permissions","accounts.RoleCapability"),
    ("user_roles","accounts.UserRole"),
    ("customers","scheduling.Customer"),
    ("professionals","scheduling.Professional"),
    ("services","scheduling.Service"),
    ("appointments","scheduling.Appointment"),
    ("modules","billing.Module"),
    ("plans","billing.Plan"),
    ("plan_modules","billing.PlanModule"),
    ("tenant_modules","billing.TenantModule"),
    ("subscriptions","billing.Subscription"),
    ("payments","billing.Payment"),
    ("customer_package_usage","engagement.CustomerPackageUsage"),
    ("settings","operations.PlatformSetting"),
    ("payment_gateways","billing.PaymentGateway"),
    ("tenant_payment_connections","billing.TenantPaymentConnection"),
    ("platform_bank_accounts","finance.PlatformBankAccount"),
    ("medical_record_entries","healthcare.MedicalRecordEntry"),
]

TRANSFORMED={
    "sports_price_rule_extensions":"campos incorporados em arena.PriceRule",
    "terms_acceptances":"normalizado em legal.LegalAcceptance",
}

IGNORED={}


class Command(BaseCommand):
    help="Compara o MySQL legado com PostgreSQL e valida cobertura de todas as tabelas."

    def add_arguments(self,parser):
        parser.add_argument("--strict",action="store_true")
        parser.add_argument("--only",default="")

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
        missing=[key for key in ("host","database","user","password") if not cfg[key]]
        if missing:
            raise CommandError("Variáveis legadas ausentes: "+", ".join(missing))

        selected={x.strip() for x in options["only"].split(",") if x.strip()}
        spec_by_table={spec["table"]:spec for spec in SPECS}
        spec_pairs=[(spec["table"],spec["model"]) for spec in SPECS]
        pairs=DIRECT+spec_pairs
        seen=set()
        failures=[]
        conn=pymysql.connect(**cfg)
        try:
            legacy_tables=self._legacy_tables(conn,cfg["database"])
            covered={table for table,_ in pairs}|set(TRANSFORMED)|set(IGNORED)
            uncovered=sorted(legacy_tables-covered)
            if uncovered:
                failures.append("cobertura:"+",".join(uncovered))
                self.stderr.write(self.style.ERROR(
                    "Tabelas sem estratégia de migração: "+", ".join(uncovered)
                ))

            for table,label in pairs:
                if table in seen or (selected and table not in selected):
                    continue
                seen.add(table)
                if table not in legacy_tables:
                    self.stdout.write(f"{table}: ausente no legado; ignorando")
                    continue
                legacy_count,legacy_hash=self._legacy_count_hash(conn,table,cfg["database"])
                model=apps.get_model(label)
                if table in spec_by_table:
                    unmapped=self._unmapped_columns(
                        model=model,
                        spec=spec_by_table[table],
                        source_columns=legacy_tables[table],
                    )
                    if unmapped:
                        failures.append(table+":colunas")
                        self.stderr.write(self.style.ERROR(
                            f"{table}: colunas sem destino no Django: {', '.join(unmapped)}"
                        ))
                target_count=model.objects.count()
                target_hash=None
                if self._integer_pk(model):
                    target_hash=self._hash(
                        model.objects.order_by("pk").values_list("pk",flat=True)
                    )
                ids_match=legacy_hash is None or target_hash is None or legacy_hash==target_hash
                ok=legacy_count==target_count and ids_match
                extra=""
                if legacy_hash is not None and target_hash is not None:
                    extra=f" ids={'OK' if ids_match else 'DIVERGENTES'}"
                self.stdout.write(
                    f"{table}: legado={legacy_count} django={target_count} "
                    f"{'OK' if ok else 'DIVERGENTE'}{extra}"
                )
                if not ok:
                    failures.append(table)

            for table,note in TRANSFORMED.items():
                if table in legacy_tables and (not selected or table in selected):
                    count=self._legacy_count(conn,table)
                    self.stdout.write(
                        self.style.WARNING(f"{table}: {count} registros · TRANSFORMADO · {note}")
                    )
            for table,note in IGNORED.items():
                if table in legacy_tables and (not selected or table in selected):
                    count=self._legacy_count(conn,table)
                    self.stdout.write(f"{table}: {count} registros · IGNORADO INTENCIONALMENTE · {note}")
        finally:
            conn.close()

        if failures:
            message="Divergências encontradas: "+", ".join(failures)
            if options["strict"]:
                raise CommandError(message)
            self.stderr.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Paridade aprovada: cobertura integral das tabelas de negócio e nenhuma divergência direta."
            ))

    def _legacy_tables(self,conn,database):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME,ORDINAL_POSITION",
                (database,),
            )
            result={}
            for row in cur.fetchall():
                result.setdefault(row["TABLE_NAME"],set()).add(row["COLUMN_NAME"])
            return result

    def _legacy_count(self,conn,table):
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) n FROM `{table}`")
            return int(cur.fetchone()["n"])

    def _legacy_count_hash(self,conn,table,database):
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) n FROM `{table}`")
            count=int(cur.fetchone()["n"])
            cur.execute(
                "SELECT COUNT(*) n FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME='id'",
                (database,table),
            )
            if not cur.fetchone()["n"]:
                return count,None
            cur.execute(f"SELECT id FROM `{table}` ORDER BY id")
            return count,self._hash([row["id"] for row in cur.fetchall()])

    def _unmapped_columns(self,model,spec,source_columns):
        rename=spec.get("rename",{})
        mapped=set()
        for field in model._meta.concrete_fields:
            attname=field.attname
            source=rename.get(attname,attname)
            if source not in source_columns and attname.endswith("_id") and field.name in source_columns:
                source=field.name
            if source in source_columns:
                mapped.add(source)
        return sorted(set(source_columns)-mapped)

    def _integer_pk(self,model):
        return model._meta.pk.get_internal_type() in {
            "AutoField","BigAutoField","IntegerField","BigIntegerField",
            "PositiveIntegerField","PositiveBigIntegerField","SmallIntegerField",
        }

    def _hash(self,values):
        digest=hashlib.sha256()
        for value in values:
            digest.update((str(value)+"\n").encode())
        return digest.hexdigest()
