import json
import os
from datetime import timezone as dt_timezone

import pymysql
from django.apps import apps
from django.core.management.base import BaseCommand,CommandError
from django.db import models,transaction
from django.utils import timezone

from core.crypto import encrypt_json, encrypt_text
from core.legacy_crypto import decrypt_php_aes_gcm


def aware(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        return value
    return timezone.make_aware(value,dt_timezone.utc)


SPECS=[
    {"table":"appointment_reminder_log","model":"scheduling.AppointmentReminderLog"},
    {"table":"appointment_reschedule_history","model":"scheduling.AppointmentRescheduleHistory"},
    {"table":"audit_logs","model":"core.AuditLog","rename":{"before":"before_json","after":"after_json"}},
    {"table":"professional_availability","model":"scheduling.ProfessionalAvailability"},
    {"table":"professional_breaks","model":"scheduling.ProfessionalBreak"},
    {"table":"professional_services","model":"scheduling.ProfessionalService","keys":["professional_id","service_id"]},
    {"table":"professional_time_off","model":"scheduling.ProfessionalTimeOff"},
    {"table":"tenant_schedule_settings","model":"scheduling.TenantScheduleSettings","keys":["tenant_id"]},
    {"table":"financial_transactions","model":"finance.FinancialTransaction"},
    {"table":"platform_finance_categories","model":"finance.PlatformFinanceCategory"},
    {"table":"platform_financial_transactions","model":"finance.PlatformFinancialTransaction"},
    {"table":"product_events","model":"finance.ProductEvent","rename":{"metadata":"metadata_json"}},
    {"table":"checkout_sessions","model":"billing.CheckoutSession"},
    {"table":"coupons","model":"billing.Coupon"},
    {"table":"invoices","model":"billing.Invoice"},
    {"table":"subscription_history","model":"billing.SubscriptionHistory"},
    {"table":"subscription_exemptions","model":"billing.SubscriptionExemption"},
    {"table":"subscription_module_adjustments","model":"billing.SubscriptionModuleAdjustment"},
    {"table":"subscription_notice_log","model":"billing.SubscriptionNoticeLog"},
    {"table":"module_requests","model":"billing.ModuleRequest"},
    {"table":"tenant_module_addons","model":"billing.TenantModuleAddon"},
    {"table":"webhook_events","model":"billing.WebhookEvent","rename":{"payload":"payload_json"}},
    {"table":"provider_events","model":"billing.ProviderEvent"},
    {"table":"pix_charges","model":"billing.PixCharge"},
    {"table":"tenant_payment_transactions","model":"billing.TenantPaymentTransaction"},
    {"table":"tenant_payment_webhook_events","model":"billing.TenantPaymentWebhookEvent"},
    {"table":"tenant_recurring_subscriptions","model":"billing.TenantRecurringSubscription"},
    {"table":"login_history","model":"accounts.LoginHistory"},
    {"table":"login_audit","model":"accounts.LoginAudit"},
    {"table":"security_events","model":"accounts.SecurityEvent","rename":{"metadata":"metadata_json"}},
    {"table":"user_blocks","model":"accounts.UserBlock"},
    {"table":"two_factor_recovery_codes","model":"accounts.RecoveryCode"},
    {"table":"two_factor_trusted_devices","model":"accounts.TrustedDevice","rename":{"verifier_hash":"validator_hash","label":"device_label"}},
    {"table":"tenant_onboarding","model":"tenants.TenantOnboarding","keys":["tenant_id"]},
    {"table":"tenant_status_history","model":"tenants.TenantStatusHistory"},
    {"table":"data_import_jobs","model":"operations.DataImportJob","rename":{"summary":"summary_json"}},
    {"table":"billing_support_requests","model":"operations.BillingSupportRequest"},
    {"table":"behavior_profiles","model":"engagement.BehaviorProfile","rename":{"intervals":"intervals_json"}},
    {"table":"behavior_service_profiles","model":"engagement.BehaviorServiceProfile","rename":{"intervals":"intervals_json"}},
    {"table":"behavior_events","model":"engagement.BehaviorEvent","rename":{"payload":"payload_json"}},
    {"table":"platform_automation_log","model":"engagement.PlatformAutomationLog"},
    {"table":"marketing_campaign_referrers","model":"communications.MarketingCampaignReferrer","keys":["campaign_id"]},
    {"table":"public_reviews","model":"contenthub.PublicReview"},
    {"table":"sports_dynamic_pricing_audit","model":"arena.DynamicPricingAudit","rename":{"details":"details_json"}},

    {"table":"financial_categories","model":"finance.FinancialCategory"},
    {"table":"cash_sessions","model":"finance.CashSession"},
    {"table":"professional_commissions","model":"finance.ProfessionalCommission"},
    {"table":"products","model":"finance.Product","rename":{"unit_label":"unit"}},
    {"table":"sales","model":"finance.Sale"},
    {"table":"sale_items","model":"finance.SaleItem"},
    {"table":"product_stock_movements","model":"finance.ProductStockMovement"},

    {"table":"service_packages","model":"engagement.ServicePackage"},
    {"table":"service_package_items","model":"engagement.PackageItem","keys":["package_id","service_id"],"rename":{"credits":"quantity"}},
    {"table":"customer_packages","model":"engagement.CustomerPackage","rename":{"purchase_amount":"paid_amount"},"map":{"status":{"used":"exhausted"}}},
    {"table":"customer_memberships","model":"engagement.CustomerMembership"},
    {"table":"tenant_loyalty_settings","model":"engagement.TenantLoyaltySettings","keys":["tenant_id"]},
    {"table":"loyalty_accounts","model":"engagement.LoyaltyAccount","keys":["tenant_id","customer_id"]},
    {"table":"loyalty_transactions","model":"engagement.LoyaltyTransaction"},
    {"table":"loyalty_rewards","model":"engagement.LoyaltyReward"},
    {"table":"loyalty_referrals","model":"engagement.LoyaltyReferral","rename":{"referrer_id":"referrer_customer_id","referred_id":"referred_customer_id"}},
    {"table":"waitlist_entries","model":"engagement.WaitlistEntry"},
    {"table":"tenant_domains","model":"engagement.TenantDomain"},
    {"table":"marketing_referral_profiles","model":"engagement.ReferralProfile","keys":["user_id"]},
    {"table":"marketing_referral_visits","model":"engagement.ReferralVisit"},

    {"table":"professional_service_commissions","model":"barber.ProfessionalServiceCommission"},
    {"table":"professional_compensation_models","model":"barber.ProfessionalCompensationModel","keys":["professional_id"]},
    {"table":"professional_goals","model":"barber.ProfessionalGoal"},
    {"table":"barber_commands","model":"barber.BarberCommand"},
    {"table":"barber_command_items","model":"barber.BarberCommandItem"},
    {"table":"barber_command_payments","model":"barber.BarberCommandPayment"},
    {"table":"barber_queue_entries","model":"barber.BarberQueueEntry"},

    {"table":"customer_vehicles","model":"auto.Vehicle","rename":{"brand":"make"}},
    {"table":"auto_settings","model":"auto.AutoSettings","keys":["tenant_id"]},
    {"table":"auto_vehicle_profiles","model":"auto.VehicleProfile","keys":["vehicle_id"]},
    {"table":"auto_service_bays","model":"auto.ServiceBay"},
    {"table":"auto_bay_hours","model":"auto.BayHours"},
    {"table":"auto_bay_services","model":"auto.BayService","keys":["bay_id","service_id"]},
    {"table":"auto_jobs","model":"auto.Job"},
    {"table":"auto_job_status_history","model":"auto.JobStatusHistory"},
    {"table":"auto_job_inspection_items","model":"auto.InspectionItem"},
    {"table":"auto_job_photos","model":"auto.JobPhoto","rename":{"file":"file_path"}},
    {"table":"auto_job_material_usage","model":"auto.JobMaterialUsage"},
    {"table":"auto_job_technical_details","model":"auto.JobTechnicalDetail","keys":["job_id"]},
    {"table":"auto_estimates","model":"auto.Estimate"},
    {"table":"auto_estimate_items","model":"auto.EstimateItem"},
    {"table":"auto_commands","model":"auto.AutoCommand"},
    {"table":"auto_command_items","model":"auto.AutoCommandItem"},
    {"table":"auto_command_payments","model":"auto.AutoCommandPayment"},
    {"table":"auto_service_materials","model":"auto.ServiceMaterial","keys":["service_id","product_id"]},
    {"table":"auto_service_steps","model":"auto.ServiceStep"},
    {"table":"auto_job_steps","model":"auto.JobStep"},
    {"table":"auto_vehicle_package_links","model":"auto.VehiclePackageLink","keys":["customer_package_id"]},
    {"table":"auto_membership_vehicle_links","model":"auto.MembershipVehicleLink","keys":["membership_id"]},
    {"table":"auto_vehicle_maintenance","model":"auto.VehicleMaintenance"},
    {"table":"auto_delivery_terms","model":"auto.DeliveryTerm","keys":["job_id"]},
    {"table":"auto_crm_events","model":"auto.CRMEvent"},

    {"table":"sports_settings","model":"arena.SportsSettings","keys":["tenant_id"]},
    {"table":"sports_arena_settings","model":"arena.ArenaSettings","keys":["tenant_id"]},
    {"table":"sports_modalities","model":"arena.Modality"},
    {"table":"sports_courts","model":"arena.Court","rename":{"photo":"photo_path"}},
    {"table":"sports_court_modalities","model":"arena.CourtModality","keys":["court_id","modality_id"]},
    {"table":"sports_court_hours","model":"arena.CourtHours"},
    {"table":"sports_price_rules","model":"arena.PriceRule"},
    {"table":"sports_court_blocks","model":"arena.CourtBlock"},
    {"table":"sports_reservations","model":"arena.Reservation","rename":{"pricing_details":"pricing_details_json"}},
    {"table":"sports_reservation_finance","model":"arena.ReservationFinance","keys":["reservation_id"]},
    {"table":"sports_reservation_history","model":"arena.ReservationHistory"},
    {"table":"sports_memberships","model":"arena.Membership"},
    {"table":"sports_membership_conflicts","model":"arena.MembershipConflict"},
    {"table":"sports_membership_reservations","model":"arena.MembershipReservation","keys":["membership_id","reservation_id"]},
    {"table":"sports_games","model":"arena.Game"},
    {"table":"sports_game_players","model":"arena.GamePlayer"},
    {"table":"sports_waitlist","model":"arena.WaitlistEntry"},
    {"table":"sports_classes","model":"arena.SportsClass"},
    {"table":"sports_class_students","model":"arena.ClassStudent","rename":{"sports_class_id":"class_id"}},
    {"table":"sports_class_attendance","model":"arena.ClassAttendance","rename":{"sports_class_id":"class_id"}},
    {"table":"sports_class_makeups","model":"arena.ClassMakeup"},
    {"table":"sports_class_billing_log","model":"arena.ClassBillingLog"},
    {"table":"sports_tournaments","model":"arena.Tournament"},
    {"table":"sports_tournament_teams","model":"arena.TournamentTeam"},
    {"table":"sports_tournament_team_players","model":"arena.TournamentTeamPlayer","keys":["team_id","customer_id"]},
    {"table":"sports_tournament_matches","model":"arena.TournamentMatch"},
    {"table":"sports_tournament_events","model":"arena.TournamentEvent"},
    {"table":"sports_customer_metrics","model":"arena.CustomerMetric","keys":["tenant_id","customer_id"]},
    {"table":"sports_automation_logs","model":"arena.AutomationLog"},
    {"table":"sports_commands","model":"arena.ArenaCommand"},
    {"table":"sports_command_items","model":"arena.ArenaCommandItem"},
    {"table":"sports_command_stock_movements","model":"arena.ArenaCommandStockMovement"},

    {"table":"notifications","model":"communications.Notification"},
    {"table":"user_notifications","model":"communications.UserNotification"},
    {"table":"campaigns","model":"communications.CustomerCampaign"},
    {"table":"campaign_recipients","model":"communications.CampaignRecipient"},
    {"table":"revenue_attributions","model":"communications.RevenueAttribution"},
    {"table":"marketing_leads","model":"communications.MarketingLead"},
    {"table":"marketing_campaigns","model":"communications.MarketingCampaign"},
    {"table":"marketing_deliveries","model":"communications.MarketingDelivery"},
    {"table":"whatsapp_conversations","model":"communications.WhatsAppConversation","rename":{"context":"context_json"}},
    {"table":"whatsapp_messages","model":"communications.WhatsAppMessage"},

    {"table":"commercial_profiles","model":"commercial.CommercialProfile","keys":["user_id"]},
    {"table":"commercial_leads","model":"commercial.Lead"},
    {"table":"commercial_lead_history","model":"commercial.LeadHistory"},
    {"table":"commercial_proposals","model":"commercial.Proposal","rename":{"modules":"modules_json","features":"features_json"}},
    {"table":"proposal_acceptances","model":"commercial.ProposalAcceptance","keys":["proposal_id"],"rename":{"proposal_snapshot":"proposal_snapshot_json"}},
    {"table":"commercial_commissions","model":"commercial.CommercialCommission"},
    {"table":"lead_privacy_events","model":"commercial.LeadPrivacyEvent","rename":{"metadata":"metadata_json"}},

    {"table":"legal_documents","model":"legal.LegalDocument"},
    {"table":"legal_acceptances","model":"legal.LegalAcceptance"},
    {"table":"customer_consents","model":"legal.CustomerConsent"},
    {"table":"support_tickets","model":"operations.SupportTicket"},
    {"table":"support_messages","model":"operations.SupportMessage","rename":{"attachment":"attachment_path"}},
    {"table":"support_access_sessions","model":"operations.SupportAccessSession","rename":{"actions":"actions_json"}},
    {"table":"backups","model":"operations.Backup"},
    {"table":"backup_verifications","model":"operations.BackupVerification"},
    {"table":"homologation_runs","model":"operations.HomologationRun","rename":{"results":"results_json"}},
    {"table":"platform_operation_settings","model":"operations.PlatformOperationSettings","keys":["id"]},
    {"table":"operational_incidents","model":"operations.OperationalIncident"},
    {"table":"cron_heartbeats","model":"operations.CronHeartbeat"},
    {"table":"cron_alert_log","model":"operations.CronAlertLog"},
    {"table":"blog_posts","model":"contenthub.BlogPost","rename":{"cover":"cover_path"}},

    {"table":"acquisition_events","model":"growth.AcquisitionEvent"},
    {"table":"meta_conversion_log","model":"growth.MetaConversionLog"},
    {"table":"public_content_translations","model":"growth.PublicContentTranslation"},
]


class Command(BaseCommand):
    help="Importa módulos especializados do MySQL legado após import_legacy_core."

    def add_arguments(self,parser):
        parser.add_argument("--dry-run",action="store_true")
        parser.add_argument("--only",default="",help="Lista separada por vírgula de tabelas legadas.")
        parser.add_argument("--skip-sensitive",action="store_true")

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
        selected={x.strip() for x in options["only"].split(",") if x.strip()}

        conn=pymysql.connect(**cfg)
        self.tables=self._load_tables(conn)
        self.legacy_key=os.getenv("LEGACY_APP_KEY","")
        total=0
        try:
            with transaction.atomic():
                if not options["skip_sensitive"]:
                    total+=self._platform_settings(conn,selected)
                    total+=self._payment_gateways(conn,selected)
                    total+=self._tenant_payment_connections(conn,selected)
                    total+=self._platform_bank_accounts(conn,selected)
                for spec in SPECS:
                    if selected and spec["table"] not in selected:
                        continue
                    if spec["table"] not in self.tables:
                        self.stdout.write(f"{spec['table']}: ausente; ignorando")
                        continue
                    imported=self._copy(conn,spec)
                    total+=imported
                    self.stdout.write(f"{spec['table']}: {imported}")
                total+=self._customer_package_usage(conn,selected)
                total+=self._sports_price_rule_extensions(conn,selected)
                total+=self._terms_acceptances(conn,selected)
                if not options["skip_sensitive"]:
                    total+=self._medical_records(conn,selected)
                if options["dry_run"]:
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING(
                        f"DRY-RUN concluído: {total} registros avaliados; nada persistido."
                    ))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"Importação especializada concluída: {total} registros."
                    ))
        finally:
            conn.close()

    def _load_tables(self,conn):
        db=conn.db.decode() if isinstance(conn.db,bytes) else conn.db
        with conn.cursor() as cur:
            cur.execute("""
                SELECT TABLE_NAME,COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s
            """,(db,))
            out={}
            for row in cur.fetchall():
                out.setdefault(row["TABLE_NAME"],set()).add(row["COLUMN_NAME"])
            return out

    def _rows(self,conn,table):
        if not table.replace("_","").isalnum():
            raise CommandError("Nome de tabela legado inválido.")
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM "+table)
            return cur.fetchall()

    def _normalize(self,field,value):
        if value is None:
            return None
        if isinstance(field,models.JSONField):
            if isinstance(value,str):
                if not value.strip():
                    return {} if field.default is dict else []
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return {"legacy":value}
            return value
        if isinstance(field,models.BooleanField):
            return bool(value)
        if isinstance(field,models.DateTimeField):
            return aware(value)
        if isinstance(field,models.UUIDField):
            return value or None
        return value

    def _copy(self,conn,spec):
        model=apps.get_model(spec["model"])
        rename=spec.get("rename",{})
        mappings=spec.get("map",{})
        fields={field.attname:field for field in model._meta.concrete_fields}
        rows=self._rows(conn,spec["table"])
        count=0
        for row in rows:
            defaults={}
            for attname,field in fields.items():
                if field.primary_key:
                    continue
                source=rename.get(attname,attname)
                if source not in row and attname.endswith("_id") and field.name in row:
                    source=field.name
                if source not in row:
                    continue
                value=row.get(source)
                if attname in mappings:
                    value=mappings[attname].get(value,value)
                defaults[attname]=self._normalize(field,value)

            keys=spec.get("keys")
            if keys:
                lookup={}
                for key in keys:
                    target=next((dst for dst,src in rename.items() if src==key),key)
                    lookup[target]=(
                        self._normalize(fields[target],row.get(key))
                        if target in fields else row.get(key)
                    )
            elif "id" in row and "id" in fields:
                lookup={"id":row["id"]}
            else:
                self.stderr.write(f"{spec['table']}: sem chave de importação; ignorando linha")
                continue

            try:
                obj,_=model.objects.update_or_create(defaults=defaults,**lookup)
            except Exception as exc:
                raise CommandError(
                    f"{spec['table']} -> {spec['model']} falhou para {lookup}: {exc}"
                ) from exc
            self._restore_times(model,obj.pk,row)
            count+=1
        return count

    def _restore_times(self,model,pk,row):
        values={}
        field_names={field.name for field in model._meta.fields}
        if "created_at" in field_names and row.get("created_at"):
            values["created_at"]=aware(row["created_at"])
        if "updated_at" in field_names and row.get("updated_at"):
            values["updated_at"]=aware(row["updated_at"])
        if values:
            model.objects.filter(pk=pk).update(**values)

    def _customer_package_usage(self,conn,selected):
        table="customer_package_usage"
        if selected and table not in selected:
            return 0
        if table not in self.tables:
            return 0
        Model=apps.get_model("engagement.CustomerPackageUsage")
        Package=apps.get_model("engagement.CustomerPackage")
        count=0
        for row in self._rows(conn,table):
            package=Package.objects.filter(pk=row["customer_package_id"]).first()
            if not package:
                continue
            Model.objects.update_or_create(
                id=row["id"],
                defaults={
                    "customer_package_id":row["customer_package_id"],
                    "tenant_id":package.tenant_id,
                    "service_id":row["service_id"],
                    "appointment_id":row.get("appointment_id"),
                    "credits_used":row.get("quantity") or 1,
                },
            )
            count+=1
        return count

    def _selected_table(self,table,selected):
        return (not selected or table in selected) and table in self.tables

    def _legacy_secret_value(self,value):
        if not value:
            return ""
        if not self.legacy_key:
            raise CommandError("LEGACY_APP_KEY é obrigatório para recriptografar segredos do legado.")
        payload=decrypt_php_aes_gcm(value,self.legacy_key)
        for key in ("value","secret","token","access_token"):
            if key in payload and not isinstance(payload[key],(dict,list)):
                return str(payload[key])
        if len(payload)==1:
            only=next(iter(payload.values()))
            if not isinstance(only,(dict,list)):
                return str(only)
        return json.dumps(payload,ensure_ascii=False,separators=(",",":"))

    def _legacy_secret_dict(self,value):
        if not value:
            return {}
        if not self.legacy_key:
            raise CommandError("LEGACY_APP_KEY é obrigatório para recriptografar credenciais do legado.")
        payload=decrypt_php_aes_gcm(value,self.legacy_key)
        raw=payload.get("value")
        if isinstance(raw,dict):
            return raw
        if isinstance(raw,str):
            try:
                decoded=json.loads(raw)
                if isinstance(decoded,dict):
                    return decoded
            except json.JSONDecodeError:
                pass
        return payload

    def _platform_settings(self,conn,selected):
        table="settings"
        if not self._selected_table(table,selected):
            return 0
        Model=apps.get_model("operations.PlatformSetting")
        count=0
        for row in self._rows(conn,table):
            value=row.get("setting_value") or ""
            if row.get("is_secret"):
                value=encrypt_text(self._legacy_secret_value(value))
            obj,_=Model.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row.get("tenant_id"),
                    "key":row["setting_key"],
                    "value":value,
                    "is_secret":bool(row.get("is_secret")),
                },
            )
            Model.objects.filter(pk=obj.pk).update(updated_at=aware(row.get("updated_at")))
            count+=1
        self.stdout.write(f"settings: {count}")
        return count

    def _payment_gateways(self,conn,selected):
        table="payment_gateways"
        if not self._selected_table(table,selected):
            return 0
        Model=apps.get_model("billing.PaymentGateway")
        settings_rows={}
        if "settings" in self.tables:
            for item in self._rows(conn,"settings"):
                if not item.get("is_secret"):
                    settings_rows[item["setting_key"]]=item.get("setting_value") or ""
        count=0
        for row in self._rows(conn,table):
            access=encrypt_text(self._legacy_secret_value(row.get("access_token_encrypted")))
            webhook_secret=encrypt_text(self._legacy_secret_value(row.get("webhook_secret_encrypted")))
            webhook_url=settings_rows.get(
                f"mercadopago.webhook_url.{row['environment']}",
                "https://localhost/webhooks/mercadopago/",
            )
            obj,_=Model.objects.update_or_create(
                id=row["id"],
                defaults={
                    "provider":row.get("provider") or "mercadopago",
                    "environment":row.get("environment") or "sandbox",
                    "public_key":row.get("public_key") or "",
                    "access_token_encrypted":access,
                    "webhook_secret_encrypted":webhook_secret,
                    "webhook_url":webhook_url,
                    "active":bool(row.get("active")),
                    "last_tested_at":aware(row.get("last_tested_at")),
                    "last_test_status":row.get("last_test_status") or "not_validated",
                },
            )
            Model.objects.filter(pk=obj.pk).update(updated_at=aware(row.get("updated_at")))
            count+=1
        self.stdout.write(f"payment_gateways: {count}")
        return count

    def _tenant_payment_connections(self,conn,selected):
        table="tenant_payment_connections"
        if not self._selected_table(table,selected):
            return 0
        Model=apps.get_model("billing.TenantPaymentConnection")
        count=0
        for row in self._rows(conn,table):
            credentials=encrypt_json(self._legacy_secret_dict(row.get("credentials_encrypted")))
            metadata=row.get("metadata_json")
            if isinstance(metadata,str):
                try: metadata=json.loads(metadata) if metadata.strip() else {}
                except json.JSONDecodeError: metadata={}
            obj,_=Model.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "provider":row.get("provider") or "mercadopago",
                    "display_name":row.get("display_name") or "Mercado Pago",
                    "environment":row.get("environment") or "sandbox",
                    "credentials_encrypted":credentials,
                    "metadata":metadata or {},
                    "status":row.get("status") or "pending",
                    "last_tested_at":aware(row.get("last_tested_at")),
                    "last_sync_at":aware(row.get("last_sync_at")),
                    "last_error_code":row.get("last_error_code") or "",
                    "created_by_id":row.get("created_by"),
                },
            )
            self._restore_times(Model,obj.pk,row)
            count+=1
        self.stdout.write(f"tenant_payment_connections: {count}")
        return count

    def _platform_bank_accounts(self,conn,selected):
        table="platform_bank_accounts"
        if not self._selected_table(table,selected):
            return 0
        Model=apps.get_model("finance.PlatformBankAccount")
        encrypted_fields=("agency_encrypted","account_encrypted","holder_document_encrypted","pix_key_encrypted","notes_encrypted")
        count=0
        for row in self._rows(conn,table):
            defaults={}
            for field in Model._meta.concrete_fields:
                if field.primary_key:
                    continue
                source=field.attname
                if source not in row and source.endswith("_id") and field.name in row:
                    source=field.name
                if source not in row:
                    continue
                value=row.get(source)
                if field.name in encrypted_fields:
                    value=encrypt_text(self._legacy_secret_value(value)) if value else ""
                defaults[field.attname]=self._normalize(field,value)
            obj,_=Model.objects.update_or_create(id=row["id"],defaults=defaults)
            self._restore_times(Model,obj.pk,row)
            count+=1
        self.stdout.write(f"platform_bank_accounts: {count}")
        return count

    def _sports_price_rule_extensions(self,conn,selected):
        table="sports_price_rule_extensions"
        if not self._selected_table(table,selected):
            return 0
        Model=apps.get_model("arena.PriceRule")
        count=0
        for row in self._rows(conn,table):
            updated=Model.objects.filter(pk=row["price_rule_id"]).update(
                rule_type=row.get("rule_type") or "standard",
                specific_date=row.get("specific_date"),
                valid_from=row.get("valid_from"),
                valid_to=row.get("valid_to"),
                minimum_duration_minutes=row.get("minimum_duration_minutes"),
                maximum_duration_minutes=row.get("maximum_duration_minutes"),
                label=row.get("label") or "",
            )
            count+=updated
        self.stdout.write(f"sports_price_rule_extensions: {count}")
        return count

    def _terms_acceptances(self,conn,selected):
        table="terms_acceptances"
        if not self._selected_table(table,selected):
            return 0
        Document=apps.get_model("legal.LegalDocument")
        Acceptance=apps.get_model("legal.LegalAcceptance")
        count=0
        for row in self._rows(conn,table):
            document=Document.objects.filter(type="terms",version=row["terms_version"]).first()
            if not document:
                self.stderr.write(
                    f"terms_acceptances #{row['id']}: documento {row['terms_version']} não encontrado; ignorando"
                )
                continue
            obj,_=Acceptance.objects.update_or_create(
                user_id=row["user_id"],document=document,
                defaults={
                    "tenant_id":row.get("tenant_id"),
                    "ip_address":row.get("ip_address") or None,
                    "user_agent":"",
                },
            )
            Acceptance.objects.filter(pk=obj.pk).update(accepted_at=aware(row["accepted_at"]))
            count+=1
        self.stdout.write(f"terms_acceptances: {count}")
        return count

    def _medical_records(self,conn,selected):
        table="medical_record_entries"
        if selected and table not in selected:
            return 0
        if table not in self.tables:
            return 0
        if not self.legacy_key:
            raise CommandError(
                "LEGACY_APP_KEY é obrigatório para recriptografar prontuários. "
                "Use --skip-sensitive somente para um ensaio sem prontuários."
            )
        Entry=apps.get_model("healthcare.MedicalRecordEntry")
        count=0
        for row in self._rows(conn,table):
            legacy=row.get("content_encrypted") or ""
            try:
                payload=decrypt_php_aes_gcm(legacy,self.legacy_key)
                plaintext=(
                    payload.get("content")
                    or payload.get("value")
                    or payload.get("text")
                    or json.dumps(payload,ensure_ascii=False)
                )
            except Exception as exc:
                raise CommandError(
                    f"Prontuário legado #{row['id']} não pôde ser descriptografado: {exc}"
                ) from exc
            Entry.objects.update_or_create(
                id=row["id"],
                defaults={
                    "tenant_id":row["tenant_id"],
                    "customer_id":row["customer_id"],
                    "professional_id":row["professional_id"],
                    "appointment_id":row.get("appointment_id"),
                    "record_type":row.get("record_type") or "evolution",
                    "title":row.get("title") or "Registro migrado",
                    "content_encrypted":encrypt_text(str(plaintext)),
                    "created_by_id":row["created_by"],
                },
            )
            Entry.objects.filter(pk=row["id"]).update(created_at=aware(row["created_at"]))
            count+=1
        return count
