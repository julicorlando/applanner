import json
import os
from datetime import timezone as dt_timezone
from decimal import Decimal

import pymysql
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Capability, PlatformRole, RoleCapability, User, UserRole
from accounts.security import encrypt_secret
from billing.models import Module, Payment, Plan, PlanModule, Subscription, TenantModule
from core.legacy_crypto import decrypt_php_aes_gcm
from scheduling.models import Appointment, Customer, Professional, Service
from tenants.models import Tenant, Unit


ROLE_PRIORITY=["master","support","commercial","manager","professional","user"]


def pick_role(value):
    roles=[r.strip() for r in (value or "").split(",") if r.strip()]
    for preferred in ROLE_PRIORITY:
        if preferred in roles:
            return preferred
    return roles[0] if roles else "user"


def aware(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        return value
    return timezone.make_aware(value,dt_timezone.utc)


class Command(BaseCommand):
    help="Importa o núcleo do MySQL legado para PostgreSQL/Django, preservando IDs quando possível."

    def add_arguments(self,parser):
        parser.add_argument("--dry-run",action="store_true")
        parser.add_argument("--skip-2fa",action="store_true")
        parser.add_argument("--catalog-only",action="store_true",help="Importa somente módulos, planos e vínculos comerciais.")

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
            raise CommandError(f"Variáveis do MySQL legado ausentes: {', '.join(missing)}")

        conn=pymysql.connect(**cfg)
        self.columns=self._load_columns(conn)

        try:
            with transaction.atomic():
                if options["catalog_only"]:
                    self._modules(conn)
                    self._plans(conn)
                    self._plan_modules(conn)
                    self._tenant_modules(conn)
                else:
                    self._tenants(conn)
                    self._units(conn)
                    self._rbac(conn)
                    self._users(conn,skip_2fa=options["skip_2fa"])
                    self._customers(conn)
                    self._professionals(conn)
                    self._services(conn)
                    self._appointments(conn)
                    self._modules(conn)
                    self._plans(conn)
                    self._plan_modules(conn)
                    self._tenant_modules(conn)
                    self._subscriptions(conn)
                    self._payments(conn)

                if options["dry_run"]:
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING("DRY-RUN concluído: nenhuma alteração persistida."))
                else:
                    self.stdout.write(self.style.SUCCESS("Importação do núcleo concluída."))
        finally:
            conn.close()

    def _load_columns(self,conn):
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TABLE_NAME,COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s
            """,(conn.db.decode() if isinstance(conn.db,bytes) else conn.db,))
            out={}
            for row in cur.fetchall():
                out.setdefault(row["TABLE_NAME"],set()).add(row["COLUMN_NAME"])
            return out

    def _has(self,table,column):
        return column in self.columns.get(table,set())

    def _rows(self,conn,sql,params=None):
        with conn.cursor() as cur:
            cur.execute(sql,params or ())
            return cur.fetchall()

    def _restore_times(self,model,pk,row):
        field_names={field.name for field in model._meta.fields}
        values={}
        if "created_at" in field_names and row.get("created_at"):
            values["created_at"]=aware(row["created_at"])
        if "updated_at" in field_names and row.get("updated_at"):
            values["updated_at"]=aware(row["updated_at"])
        if values:
            model.objects.filter(pk=pk).update(**values)

    def _rbac(self,conn):
        if "roles" not in self.columns or "permissions" not in self.columns:
            self.stdout.write("rbac: tabelas legadas não encontradas; ignorando.")
            return

        roles=self._rows(conn,"SELECT id,slug,name FROM roles ORDER BY id")
        for row in roles:
            PlatformRole.objects.update_or_create(
                id=row["id"],
                defaults={"slug":row["slug"],"name":row["name"]},
            )

        permissions=self._rows(conn,"SELECT id,slug,name FROM permissions ORDER BY id")
        for row in permissions:
            Capability.objects.update_or_create(
                id=row["id"],
                defaults={"slug":row["slug"],"name":row["name"]},
            )

        RoleCapability.objects.all().delete()
        if "role_permissions" in self.columns:
            links=self._rows(conn,"SELECT role_id,permission_id FROM role_permissions")
            RoleCapability.objects.bulk_create([
                RoleCapability(role_id=row["role_id"],capability_id=row["permission_id"])
                for row in links
            ],ignore_conflicts=True)
        else:
            links=[]

        self.stdout.write(
            f"rbac: {len(roles)} papéis | {len(permissions)} permissões | {len(links)} vínculos"
        )

    def _tenants(self,conn):
        rows=self._rows(conn,"SELECT * FROM tenants ORDER BY id")
        for row in rows:
            defaults={
                "name":row["name"],
                "slug":row["slug"],
                "public_slug":row.get("public_slug"),
                "public_short_code":row.get("public_short_code"),
                "public_booking_enabled":bool(row.get("public_booking_enabled",1)),
                "document":row.get("document") or "",
                "email":row.get("email") or "",
                "phone":row.get("phone") or "",
                "description":row.get("description") or "",
                "category":row.get("category") or "",
                "default_locale":(row.get("default_locale") or "pt_BR").replace("_","-").lower(),
                "locale":(row.get("default_locale") or "pt_BR").replace("_","-").lower(),
                "logo":row.get("logo_path") or "",
                "cover":row.get("cover_path") or "",
                "primary_color":row.get("primary_color") or "#2563eb",
                "menu_color":row.get("menu_color") or "#17213b",
                "menu_text_color":row.get("menu_text_color") or "#dce3f7",
                "background_color":row.get("background_color") or "#f4f6fb",
                "text_color":row.get("text_color") or "#17213b",
                "font_family":row.get("font_family") or "Inter",
                "font_size":int(row.get("font_size") or 15),
                "accepted_payment_methods":self._json_value(row.get("accepted_payment_methods"),default=[]),
                "public_sections":self._json_value(row.get("public_sections"),default=[]),
                "public_layout":row.get("public_layout") or "editorial",
                "public_headline":row.get("public_headline") or "",
                "public_subheadline":row.get("public_subheadline") or "",
                "public_cta_label":row.get("public_cta_label") or "",
                "public_announcement":row.get("public_announcement") or "",
                "public_accent_color":row.get("public_accent_color") or "",
                "public_section_order":self._json_value(row.get("public_section_order"),default=[]),
                "public_seo_title":row.get("public_seo_title") or "",
                "public_seo_description":row.get("public_seo_description") or "",
                "public_instagram":row.get("public_instagram") or "",
                "public_enabled":bool(row.get("public_enabled",0)),
                "onboarding_step":int(row.get("onboarding_step") or 1),
                "status":row.get("status") or "trial",
                "deleted_at":aware(row.get("deleted_at")),
            }
            obj,_=Tenant.objects.update_or_create(id=row["id"],defaults=defaults)
            self._restore_times(Tenant,obj.pk,row)
        self.stdout.write(f"tenants: {len(rows)}")

    def _units(self,conn):
        if "units" not in self.columns:
            self.stdout.write("units: tabela legada ausente; ignorando.")
            return
        rows=self._rows(conn,"SELECT * FROM units ORDER BY id")
        for row in rows:
            obj,_=Unit.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "name":row["name"],
                    "address":row.get("address") or "",
                    "address_number":row.get("address_number") or "",
                    "address_complement":row.get("address_complement") or "",
                    "district":row.get("district") or "",
                    "city":row.get("city") or "",
                    "state":row.get("state") or "",
                    "postal_code":row.get("postal_code") or "",
                    "latitude":row.get("latitude"),
                    "longitude":row.get("longitude"),
                    "geocoded_at":aware(row.get("geocoded_at")),
                    "phone":row.get("phone") or "",
                    "whatsapp":row.get("whatsapp") or "",
                    "email":row.get("email") or "",
                    "instagram":row.get("instagram") or "",
                    "facebook":row.get("facebook") or "",
                    "tiktok":row.get("tiktok") or "",
                    "website":row.get("website") or "",
                    "map_url":row.get("map_url") or "",
                    "amenities":self._json_value(row.get("amenities"),default=[]),
                    "payment_methods":self._json_value(row.get("payment_methods"),default=[]),
                    "public_notes":row.get("public_notes") or "",
                    "is_primary":bool(row.get("is_primary",0)),
                    "active":bool(row.get("active",1)),
                },
            )
            self._restore_times(Unit,obj.pk,row)
        self.stdout.write(f"units: {len(rows)}")

    def _users(self,conn,skip_2fa=False):
        two_factor="u.two_factor_secret" if self._has("users","two_factor_secret") else "NULL AS two_factor_secret"
        enabled="u.two_factor_enabled_at" if self._has("users","two_factor_enabled_at") else "NULL AS two_factor_enabled_at"
        last_step="u.two_factor_last_step" if self._has("users","two_factor_last_step") else "0 AS two_factor_last_step"
        session_version="u.session_version" if self._has("users","session_version") else "1 AS session_version"
        must_change="u.must_change_password" if self._has("users","must_change_password") else "0 AS must_change_password"
        sql=f"""
            SELECT u.*,
                   GROUP_CONCAT(DISTINCT r.slug ORDER BY r.id SEPARATOR ',') AS role_slugs,
                   {two_factor}, {enabled}, {last_step}, {session_version}, {must_change}
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id=u.id
            LEFT JOIN roles r ON r.id=ur.role_id
            GROUP BY u.id
            ORDER BY u.id
        """
        rows=self._rows(conn,sql)
        legacy_key=os.getenv("LEGACY_APP_KEY","")
        migrated_2fa=0

        for row in rows:
            name=(row.get("name") or "").strip()
            encrypted=""
            if row.get("two_factor_secret") and not skip_2fa:
                if not legacy_key:
                    self.stderr.write(f"usuário {row['id']}: 2FA não migrado; LEGACY_APP_KEY ausente.")
                else:
                    payload=decrypt_php_aes_gcm(row["two_factor_secret"],legacy_key)
                    secret=payload.get("secret")
                    if secret:
                        encrypted=encrypt_secret(secret)
                        migrated_2fa+=1

            password=row.get("password_hash") or ""
            if password and not password.startswith("php_bcrypt$"):
                password="php_bcrypt$"+password

            user,_=User.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row.get("tenant_id"),
                    "email":(row.get("email") or "").strip().lower(),
                    "first_name":name,
                    "last_name":"",
                    "password":password,
                    "role":pick_role(row.get("role_slugs")),
                    "is_active":row.get("status","active")=="active",
                    "is_staff":pick_role(row.get("role_slugs")) in {"master","support"},
                    "must_change_password":bool(row.get("must_change_password")),
                    "session_version":int(row.get("session_version") or 1),
                    "two_factor_secret_encrypted":encrypted,
                    "two_factor_enabled_at":aware(row.get("two_factor_enabled_at")),
                    "two_factor_last_step":int(row.get("two_factor_last_step") or 0),
                    "last_login":aware(row.get("last_login_at")),
                    "date_joined":aware(row.get("created_at")) or timezone.now(),
                },
            )

            UserRole.objects.filter(user=user).delete()
            role_ids=self._rows(
                conn,
                "SELECT role_id FROM user_roles WHERE user_id=%s",
                (row["id"],),
            ) if "user_roles" in self.columns else []
            UserRole.objects.bulk_create([
                UserRole(user=user,role_id=role_row["role_id"])
                for role_row in role_ids
            ],ignore_conflicts=True)

        self.stdout.write(f"users: {len(rows)} | 2FA recriptografado: {migrated_2fa}")

    def _customers(self,conn):
        rows=self._rows(conn,"SELECT * FROM customers ORDER BY id")
        for row in rows:
            obj,_=Customer.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "name":row["name"],
                    "phone":row.get("phone") or "",
                    "email":row.get("email") or "",
                    "birth_date":row.get("birth_date"),
                    "consent_marketing":bool(row.get("consent_marketing")),
                    "active":row.get("status","active")=="active",
                },
            )
            self._restore_times(Customer,obj.pk,row)
        self.stdout.write(f"customers: {len(rows)}")

    def _professionals(self,conn):
        rows=self._rows(conn,"SELECT * FROM professionals ORDER BY id")
        for row in rows:
            obj,_=Professional.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "unit_id":row.get("unit_id"),
                    "user_id":row.get("user_id"),
                    "name":row["name"],
                    "public_slug":row.get("public_slug"),
                    "email":row.get("email") or "",
                    "phone":row.get("phone") or "",
                    "specialty":row.get("specialty") or "",
                    "photo":row.get("photo_path") or "",
                    "commission_percent":row.get("commission_percent"),
                    "active":bool(row.get("active",1)),
                },
            )
            self._restore_times(Professional,obj.pk,row)
        self.stdout.write(f"professionals: {len(rows)}")

    def _services(self,conn):
        rows=self._rows(conn,"SELECT * FROM services ORDER BY id")
        for row in rows:
            obj,_=Service.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "name":row["name"],
                    "description":row.get("description") or "",
                    "duration_minutes":row["duration_minutes"],
                    "price":Decimal(str(row.get("price") or 0)),
                    "active":bool(row.get("active",1)),
                },
            )
            self._restore_times(Service,obj.pk,row)
        self.stdout.write(f"services: {len(rows)}")

    def _appointments(self,conn):
        rows=self._rows(conn,"SELECT * FROM appointments ORDER BY id")
        for row in rows:
            obj,_=Appointment.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "customer_id":row["customer_id"],
                    "professional_id":row.get("professional_id"),
                    "service_id":row["service_id"],
                    "service_price_snapshot":row.get("service_price_snapshot"),
                    "starts_at":aware(row["starts_at"]),
                    "ends_at":aware(row["ends_at"]),
                    "status":row.get("status") or "pending",
                    "source":row.get("source") or "internal",
                    "notes":row.get("notes") or "",
                    "customer_manage_token_hash":row.get("customer_manage_token_hash"),
                    "customer_manage_token_encrypted":"",
                    "customer_confirmed_at":aware(row.get("customer_confirmed_at")),
                    "checked_in_at":aware(row.get("checked_in_at")),
                    "service_started_at":aware(row.get("service_started_at")),
                    "service_completed_at":aware(row.get("service_completed_at")),
                    "reminder_24h_sent_at":aware(row.get("reminder_24h_sent_at")),
                    "reminder_2h_sent_at":aware(row.get("reminder_2h_sent_at")),
                    "created_by_id":row.get("created_by"),
                },
            )
            self._restore_times(Appointment,obj.pk,row)
        self.stdout.write(f"appointments: {len(rows)}")

    def _modules(self,conn):
        if "modules" not in self.columns:
            self.stdout.write("modules: tabela legada ausente; ignorando.")
            return
        rows=self._rows(conn,"SELECT * FROM modules ORDER BY id")
        for row in rows:
            defaults={
                "slug":row["slug"],
                "name":row["name"],
                "description":row.get("description") or "",
                "active":bool(row.get("active",1)),
            }
            if self._has("modules","addon_monthly_price"):
                defaults["addon_monthly_price"]=(
                    Decimal(str(row["addon_monthly_price"]))
                    if row.get("addon_monthly_price") is not None else None
                )
            if self._has("modules","addon_sellable"):
                defaults["addon_sellable"]=bool(row.get("addon_sellable"))
            if self._has("modules","sort_order"):
                defaults["sort_order"]=int(row.get("sort_order") or 0)
            Module.objects.update_or_create(id=row["id"],defaults=defaults)
        self.stdout.write(f"modules: {len(rows)}")

    def _json_value(self,value,default=None):
        fallback={} if default is None else default
        if isinstance(value,str):
            if not value.strip():
                return fallback
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return fallback
        return value if value is not None else fallback

    def _plans(self,conn):
        rows=self._rows(conn,"SELECT * FROM plans ORDER BY id")
        for row in rows:
            defaults={
                "name":row["name"],
                "slug":row["slug"],
                "description":row.get("description") or "",
                "monthly_price":Decimal(str(row.get("monthly_price") or 0)),
                "active":bool(row.get("active",1)),
                "features":self._json_value(row.get("features_json")),
            }
            for source,target in (
                ("quarterly_price","quarterly_price"),
                ("semiannual_price","semiannual_price"),
                ("annual_price","annual_price"),
            ):
                if self._has("plans",source):
                    defaults[target]=(
                        Decimal(str(row[source])) if row.get(source) is not None else None
                    )
            if self._has("plans","trial_days"):
                defaults["trial_days"]=int(row.get("trial_days") or 0)
            if self._has("plans","trial_without_card"):
                defaults["trial_without_card"]=bool(row.get("trial_without_card"))
            if self._has("plans","featured"):
                defaults["featured"]=bool(row.get("featured"))
            if self._has("plans","sort_order"):
                defaults["sort_order"]=int(row.get("sort_order") or 0)
            if self._has("plans","public_visible"):
                defaults["public_visible"]=bool(row.get("public_visible"))
            if self._has("plans","is_custom"):
                defaults["is_custom"]=bool(row.get("is_custom"))
            if self._has("plans","created_by_user_id"):
                creator_id=row.get("created_by_user_id")
                defaults["created_by_id"]=creator_id if creator_id and User.objects.filter(pk=creator_id).exists() else None

            obj,_=Plan.objects.update_or_create(id=row["id"],defaults=defaults)
            self._restore_times(Plan,obj.pk,row)
        self.stdout.write(f"plans: {len(rows)}")

    def _plan_modules(self,conn):
        if "plan_modules" not in self.columns:
            self.stdout.write("plan_modules: tabela legada ausente; ignorando.")
            return
        rows=self._rows(conn,"SELECT plan_id,module_id,enabled FROM plan_modules ORDER BY plan_id,module_id")
        valid=[]
        for row in rows:
            if Plan.objects.filter(pk=row["plan_id"]).exists() and Module.objects.filter(pk=row["module_id"]).exists():
                PlanModule.objects.update_or_create(
                    plan_id=row["plan_id"],module_id=row["module_id"],
                    defaults={"enabled":bool(row.get("enabled",1))},
                )
                valid.append((row["plan_id"],row["module_id"]))
        legacy_plan_ids={plan_id for plan_id,_ in valid}
        if legacy_plan_ids:
            keep=set(valid)
            for link in PlanModule.objects.filter(plan_id__in=legacy_plan_ids):
                if (link.plan_id,link.module_id) not in keep:
                    link.delete()
        self.stdout.write(f"plan_modules: {len(valid)}")

    def _tenant_modules(self,conn):
        if "tenant_modules" not in self.columns:
            self.stdout.write("tenant_modules: tabela legada ausente; ignorando.")
            return
        rows=self._rows(conn,"SELECT tenant_id,module_id,enabled FROM tenant_modules ORDER BY tenant_id,module_id")
        count=0
        for row in rows:
            if not Tenant.objects.filter(pk=row["tenant_id"]).exists():
                continue
            if not Module.objects.filter(pk=row["module_id"]).exists():
                continue
            TenantModule.objects.update_or_create(
                tenant_id=row["tenant_id"],module_id=row["module_id"],
                defaults={"enabled":bool(row.get("enabled",1))},
            )
            count+=1
        self.stdout.write(f"tenant_modules: {count}")

    def _subscriptions(self,conn):
        rows=self._rows(conn,"SELECT * FROM subscriptions ORDER BY id")
        for row in rows:
            obj,_=Subscription.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "plan_id":row["plan_id"],
                    "billing_cycle":row.get("billing_cycle") or "monthly",
                    "contracted_price":row.get("contracted_price"),
                    "base_contracted_price":row.get("base_contracted_price"),
                    "addon_contracted_price":Decimal(str(row.get("addon_contracted_price") or 0)),
                    "status":row.get("status") or "trial",
                    "started_at":aware(row["started_at"]),
                    "trial_started_at":aware(row.get("trial_started_at")),
                    "trial_ends_at":aware(row.get("trial_ends_at")),
                    "trial_days_snapshot":row.get("trial_days_snapshot"),
                    "next_billing_at":aware(row.get("next_billing_at")),
                    "cancelled_at":aware(row.get("cancelled_at")),
                    "provider_customer_id":row.get("provider_customer_id") or "",
                    "provider_subscription_id":row.get("provider_subscription_id") or "",
                    "provider_plan_id":row.get("provider_plan_id") or "",
                },
            )
            self._restore_times(Subscription,obj.pk,row)
        self.stdout.write(f"subscriptions: {len(rows)}")

    def _payments(self,conn):
        rows=self._rows(conn,"SELECT * FROM payments ORDER BY id")
        for row in rows:
            obj,_=Payment.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "subscription_id":row.get("subscription_id"),
                    "purpose":row.get("purpose") or "subscription",
                    "reference_id":row.get("reference_id"),
                    "provider":row.get("provider") or "",
                    "environment":row.get("environment") or "unknown",
                    "provider_reference":row.get("provider_reference") or "",
                    "provider_status":row.get("provider_status") or "",
                    "provider_payment_id":row.get("provider_payment_id") or "",
                    "idempotency_key":row.get("idempotency_key") or "",
                    "amount":Decimal(str(row.get("amount") or 0)),
                    "status":row.get("status") or "pending",
                    "due_at":aware(row.get("due_at")),
                    "paid_at":aware(row.get("paid_at")),
                },
            )
            self._restore_times(Payment,obj.pk,row)
        self.stdout.write(f"payments: {len(rows)}")
