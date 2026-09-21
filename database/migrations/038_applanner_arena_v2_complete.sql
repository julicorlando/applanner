-- ApPlanner Arena V2: conclusão dos recursos internos pendentes do Arena V1.
-- Incremental e reaplicável. Não apaga dados.

ALTER TABLE sports_arena_settings
  ADD COLUMN IF NOT EXISTS dynamic_min_multiplier DECIMAL(6,3) NOT NULL DEFAULT 0.800 AFTER dynamic_pricing_enabled,
  ADD COLUMN IF NOT EXISTS dynamic_max_multiplier DECIMAL(6,3) NOT NULL DEFAULT 1.300 AFTER dynamic_min_multiplier,
  ADD COLUMN IF NOT EXISTS dynamic_last_minute_hours SMALLINT UNSIGNED NOT NULL DEFAULT 4 AFTER dynamic_max_multiplier,
  ADD COLUMN IF NOT EXISTS dynamic_last_minute_discount_percent DECIMAL(6,2) NOT NULL DEFAULT 10.00 AFTER dynamic_last_minute_hours,
  ADD COLUMN IF NOT EXISTS dynamic_high_occupancy_threshold DECIMAL(6,2) NOT NULL DEFAULT 70.00 AFTER dynamic_last_minute_discount_percent,
  ADD COLUMN IF NOT EXISTS dynamic_high_occupancy_surcharge_percent DECIMAL(6,2) NOT NULL DEFAULT 10.00 AFTER dynamic_high_occupancy_threshold,
  ADD COLUMN IF NOT EXISTS dynamic_low_occupancy_threshold DECIMAL(6,2) NOT NULL DEFAULT 30.00 AFTER dynamic_high_occupancy_surcharge_percent,
  ADD COLUMN IF NOT EXISTS dynamic_low_occupancy_discount_percent DECIMAL(6,2) NOT NULL DEFAULT 5.00 AFTER dynamic_low_occupancy_threshold,
  ADD COLUMN IF NOT EXISTS dynamic_low_demand_window_hours SMALLINT UNSIGNED NOT NULL DEFAULT 24 AFTER dynamic_low_occupancy_discount_percent,
  ADD COLUMN IF NOT EXISTS dynamic_weekend_surcharge_percent DECIMAL(6,2) NOT NULL DEFAULT 0.00 AFTER dynamic_low_demand_window_hours,
  ADD COLUMN IF NOT EXISTS dynamic_rounding_step DECIMAL(8,2) NOT NULL DEFAULT 0.01 AFTER dynamic_weekend_surcharge_percent,
  ADD COLUMN IF NOT EXISTS waitlist_email_enabled TINYINT(1) NOT NULL DEFAULT 1 AFTER allow_waitlist,
  ADD COLUMN IF NOT EXISTS waitlist_whatsapp_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER waitlist_email_enabled,
  ADD COLUMN IF NOT EXISTS reservation_reminder_enabled TINYINT(1) NOT NULL DEFAULT 1 AFTER allow_games,
  ADD COLUMN IF NOT EXISTS reservation_reminder_hours SMALLINT UNSIGNED NOT NULL DEFAULT 24 AFTER reservation_reminder_enabled,
  ADD COLUMN IF NOT EXISTS crm_return_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER reservation_reminder_hours,
  ADD COLUMN IF NOT EXISTS crm_return_days SMALLINT UNSIGNED NOT NULL DEFAULT 30 AFTER crm_return_enabled,
  ADD COLUMN IF NOT EXISTS idle_slot_campaign_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER crm_return_days,
  ADD COLUMN IF NOT EXISTS idle_slot_hours_before SMALLINT UNSIGNED NOT NULL DEFAULT 24 AFTER idle_slot_campaign_enabled;

ALTER TABLE sports_reservations
  ADD COLUMN IF NOT EXISTS base_total_amount DECIMAL(12,2) NULL AFTER total_amount,
  ADD COLUMN IF NOT EXISTS pricing_multiplier DECIMAL(8,4) NOT NULL DEFAULT 1.0000 AFTER base_total_amount,
  ADD COLUMN IF NOT EXISTS pricing_details_json LONGTEXT NULL AFTER pricing_multiplier,
  ADD COLUMN IF NOT EXISTS tournament_match_id BIGINT UNSIGNED NULL AFTER recurrence_group;

ALTER TABLE sports_waitlist
  ADD COLUMN IF NOT EXISTS notify_email TINYINT(1) NOT NULL DEFAULT 1 AFTER customer_email,
  ADD COLUMN IF NOT EXISTS notify_whatsapp TINYINT(1) NOT NULL DEFAULT 0 AFTER notify_email,
  ADD COLUMN IF NOT EXISTS offered_starts_at DATETIME NULL AFTER offered_at,
  ADD COLUMN IF NOT EXISTS offered_total DECIMAL(12,2) NULL AFTER offered_starts_at,
  ADD COLUMN IF NOT EXISTS notification_queued_at DATETIME NULL AFTER offered_total,
  ADD COLUMN IF NOT EXISTS last_notification_at DATETIME NULL AFTER notification_queued_at;

ALTER TABLE sports_class_students
  ADD COLUMN IF NOT EXISTS monthly_amount_override DECIMAL(12,2) NULL AFTER responsible_phone,
  ADD COLUMN IF NOT EXISTS billing_day TINYINT UNSIGNED NULL AFTER monthly_amount_override;

ALTER TABLE sports_tournament_teams
  ADD COLUMN IF NOT EXISTS group_name VARCHAR(40) NULL AFTER name;

ALTER TABLE sports_tournament_matches
  ADD COLUMN IF NOT EXISTS round_number SMALLINT UNSIGNED NULL AFTER phase,
  ADD COLUMN IF NOT EXISTS reservation_id BIGINT UNSIGNED NULL AFTER starts_at;

CREATE TABLE IF NOT EXISTS sports_class_makeups (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  student_id BIGINT UNSIGNED NOT NULL,
  original_class_id BIGINT UNSIGNED NOT NULL,
  original_date DATE NOT NULL,
  replacement_class_id BIGINT UNSIGNED NULL,
  replacement_date DATE NULL,
  status ENUM('credit','scheduled','used','cancelled') NOT NULL DEFAULT 'credit',
  notes VARCHAR(300) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_scmakeup_student(tenant_id,student_id,status,original_date),
  CONSTRAINT fk_scmakeup_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_scmakeup_student FOREIGN KEY(student_id) REFERENCES sports_class_students(id) ON DELETE CASCADE,
  CONSTRAINT fk_scmakeup_original_class FOREIGN KEY(original_class_id) REFERENCES sports_classes(id) ON DELETE CASCADE,
  CONSTRAINT fk_scmakeup_replacement_class FOREIGN KEY(replacement_class_id) REFERENCES sports_classes(id) ON DELETE SET NULL,
  CONSTRAINT fk_scmakeup_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_class_billing_log (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  student_id BIGINT UNSIGNED NOT NULL,
  competence_month CHAR(7) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  financial_transaction_id BIGINT UNSIGNED NULL,
  status ENUM('generated','skipped','cancelled') NOT NULL DEFAULT 'generated',
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_scbl_student_month(student_id,competence_month),
  INDEX idx_scbl_tenant(tenant_id,competence_month,status),
  CONSTRAINT fk_scbl_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_scbl_student FOREIGN KEY(student_id) REFERENCES sports_class_students(id) ON DELETE CASCADE,
  CONSTRAINT fk_scbl_finance FOREIGN KEY(financial_transaction_id) REFERENCES financial_transactions(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_dynamic_pricing_audit (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  reservation_id BIGINT UNSIGNED NOT NULL,
  base_total DECIMAL(12,2) NOT NULL,
  final_total DECIMAL(12,2) NOT NULL,
  multiplier DECIMAL(8,4) NOT NULL,
  details_json LONGTEXT NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_sdpa_reservation(reservation_id),
  INDEX idx_sdpa_tenant(tenant_id,created_at),
  CONSTRAINT fk_sdpa_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sdpa_reservation FOREIGN KEY(reservation_id) REFERENCES sports_reservations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_tournament_events (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  tournament_id BIGINT UNSIGNED NOT NULL,
  event_type VARCHAR(50) NOT NULL,
  detail VARCHAR(500) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_ste_tournament(tournament_id,created_at),
  CONSTRAINT fk_ste_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_ste_tournament FOREIGN KEY(tournament_id) REFERENCES sports_tournaments(id) ON DELETE CASCADE,
  CONSTRAINT fk_ste_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Aliases/permissões já existem no V1. A migration apenas garante que owners/managers mantenham acesso aos recursos avançados.
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('sports.academy.manage','sports.tournaments.manage','sports.waitlist.manage','sports.reports.view')
WHERE r.slug IN('owner','manager');
