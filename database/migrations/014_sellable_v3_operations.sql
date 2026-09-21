-- V3: agenda 2.0, self-service, finance, commissions, stock, vehicles, notifications, packages, loyalty, waitlist and custom domains.

ALTER TABLE appointments ADD COLUMN customer_manage_token_hash CHAR(64) NULL AFTER notes;
ALTER TABLE appointments ADD COLUMN customer_manage_token_encrypted LONGTEXT NULL AFTER customer_manage_token_hash;
ALTER TABLE appointments ADD COLUMN customer_confirmed_at DATETIME NULL AFTER customer_manage_token_encrypted;
ALTER TABLE appointments ADD COLUMN reminder_24h_sent_at DATETIME NULL AFTER customer_confirmed_at;
ALTER TABLE appointments ADD COLUMN reminder_2h_sent_at DATETIME NULL AFTER reminder_24h_sent_at;
ALTER TABLE appointments MODIFY COLUMN source ENUM('public','professional_link','internal','whatsapp','campaign','api') NOT NULL DEFAULT 'internal';
CREATE UNIQUE INDEX uq_appointment_manage_token ON appointments(customer_manage_token_hash);

CREATE TABLE IF NOT EXISTS tenant_schedule_settings (
  tenant_id BIGINT UNSIGNED PRIMARY KEY,
  minimum_notice_minutes INT UNSIGNED NOT NULL DEFAULT 30,
  maximum_days_ahead SMALLINT UNSIGNED NOT NULL DEFAULT 90,
  slot_interval_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 15,
  buffer_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  customer_can_cancel TINYINT(1) NOT NULL DEFAULT 1,
  customer_can_reschedule TINYINT(1) NOT NULL DEFAULT 1,
  cancel_notice_minutes INT UNSIGNED NOT NULL DEFAULT 120,
  reminder_24h_enabled TINYINT(1) NOT NULL DEFAULT 1,
  reminder_2h_enabled TINYINT(1) NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_tss_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS professional_breaks (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  weekday TINYINT UNSIGNED NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  label VARCHAR(100) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_pb_prof_day(tenant_id,professional_id,weekday,active),
  CONSTRAINT fk_pb_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_pb_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS professional_time_off (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  type ENUM('break','day_off','vacation','meeting','personal','other') NOT NULL DEFAULT 'other',
  starts_at DATETIME NOT NULL,
  ends_at DATETIME NOT NULL,
  reason VARCHAR(255) NULL,
  status ENUM('active','cancelled') NOT NULL DEFAULT 'active',
  created_by BIGINT UNSIGNED NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_pto_range(tenant_id,professional_id,status,starts_at,ends_at),
  CONSTRAINT fk_pto_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_pto_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE CASCADE,
  CONSTRAINT fk_pto_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS appointment_reschedule_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NOT NULL,
  old_professional_id BIGINT UNSIGNED NULL,
  new_professional_id BIGINT UNSIGNED NULL,
  old_starts_at DATETIME NOT NULL,
  old_ends_at DATETIME NOT NULL,
  new_starts_at DATETIME NOT NULL,
  new_ends_at DATETIME NOT NULL,
  reason VARCHAR(255) NULL,
  actor_type ENUM('customer','user') NOT NULL,
  actor_user_id BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_arh_appointment(tenant_id,appointment_id,created_at),
  CONSTRAINT fk_arh_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_arh_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS appointment_reminder_log (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NOT NULL,
  reminder_key VARCHAR(30) NOT NULL,
  channel ENUM('email','whatsapp') NOT NULL,
  status ENUM('queued','sent','failed','skipped') NOT NULL DEFAULT 'queued',
  error_message VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  sent_at DATETIME NULL,
  UNIQUE KEY uq_appointment_reminder(appointment_id,reminder_key,channel),
  INDEX idx_reminder_status(tenant_id,status,created_at),
  CONSTRAINT fk_arl_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_arl_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS financial_categories (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  type ENUM('income','expense','both') NOT NULL DEFAULT 'both',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_fin_category(tenant_id,name),
  CONSTRAINT fk_fc_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
ALTER TABLE financial_transactions ADD COLUMN category_id BIGINT UNSIGNED NULL AFTER appointment_id;
ALTER TABLE financial_transactions ADD COLUMN source_type VARCHAR(40) NULL AFTER category_id;
ALTER TABLE financial_transactions ADD COLUMN source_id BIGINT UNSIGNED NULL AFTER source_type;
ALTER TABLE financial_transactions ADD COLUMN payment_method VARCHAR(40) NULL AFTER amount;
ALTER TABLE financial_transactions ADD COLUMN competence_at DATE NULL AFTER payment_method;
CREATE INDEX idx_finance_source ON financial_transactions(tenant_id,source_type,source_id);

CREATE TABLE IF NOT EXISTS cash_sessions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  unit_id BIGINT UNSIGNED NULL,
  opened_by BIGINT UNSIGNED NOT NULL,
  opening_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  opened_at DATETIME NOT NULL,
  closed_by BIGINT UNSIGNED NULL,
  closing_amount DECIMAL(12,2) NULL,
  expected_amount DECIMAL(12,2) NULL,
  difference_amount DECIMAL(12,2) NULL,
  closed_at DATETIME NULL,
  status ENUM('open','closed') NOT NULL DEFAULT 'open',
  notes VARCHAR(500) NULL,
  INDEX idx_cash_tenant(tenant_id,status,opened_at),
  CONSTRAINT fk_cash_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE sale_items ADD COLUMN commission_amount_snapshot DECIMAL(12,2) NULL AFTER cost_snapshot;

CREATE TABLE IF NOT EXISTS professional_commissions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  source_type ENUM('service','product') NOT NULL,
  source_id BIGINT UNSIGNED NOT NULL,
  gross_amount DECIMAL(12,2) NOT NULL,
  rate_percent DECIMAL(5,2) NULL,
  commission_amount DECIMAL(12,2) NOT NULL,
  status ENUM('pending','paid','reversed') NOT NULL DEFAULT 'pending',
  paid_at DATETIME NULL,
  paid_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_commission_source(tenant_id,professional_id,source_type,source_id),
  INDEX idx_commission_status(tenant_id,professional_id,status,created_at),
  CONSTRAINT fk_pc_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_pc_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS customer_vehicles (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  plate VARCHAR(12) NULL,
  make VARCHAR(80) NULL,
  model VARCHAR(100) NOT NULL,
  year SMALLINT UNSIGNED NULL,
  color VARCHAR(60) NULL,
  notes VARCHAR(500) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_vehicle_plate(tenant_id,plate),
  INDEX idx_vehicle_customer(tenant_id,customer_id,active),
  CONSTRAINT fk_vehicle_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_vehicle_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
ALTER TABLE appointments ADD COLUMN vehicle_id BIGINT UNSIGNED NULL AFTER customer_id;
ALTER TABLE appointments ADD CONSTRAINT fk_appointment_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS user_notifications (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  type VARCHAR(60) NOT NULL,
  title VARCHAR(190) NOT NULL,
  message VARCHAR(500) NOT NULL,
  action_url VARCHAR(255) NULL,
  severity ENUM('info','success','warning','danger') NOT NULL DEFAULT 'info',
  read_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_un_user(user_id,read_at,created_at),
  CONSTRAINT fk_un_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
ALTER TABLE notifications ADD COLUMN provider_reference VARCHAR(190) NULL AFTER status;
ALTER TABLE notifications ADD COLUMN delivered_at DATETIME NULL AFTER sent_at;
ALTER TABLE notifications ADD COLUMN clicked_at DATETIME NULL AFTER delivered_at;
ALTER TABLE notifications ADD COLUMN error_message VARCHAR(500) NULL AFTER clicked_at;

ALTER TABLE support_tickets ADD COLUMN source_url VARCHAR(500) NULL AFTER description;
ALTER TABLE support_tickets ADD COLUMN browser_context VARCHAR(500) NULL AFTER source_url;
ALTER TABLE support_tickets ADD COLUMN app_version VARCHAR(40) NULL AFTER browser_context;
ALTER TABLE support_tickets ADD COLUMN error_id VARCHAR(60) NULL AFTER app_version;

CREATE TABLE IF NOT EXISTS service_packages (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(150) NOT NULL,
  price DECIMAL(12,2) NOT NULL,
  validity_days SMALLINT UNSIGNED NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_package_tenant(tenant_id,active),
  CONSTRAINT fk_package_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS service_package_items (
  package_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  quantity INT UNSIGNED NOT NULL,
  PRIMARY KEY(package_id,service_id),
  CONSTRAINT fk_spi_package FOREIGN KEY(package_id) REFERENCES service_packages(id) ON DELETE CASCADE,
  CONSTRAINT fk_spi_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS customer_packages (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  package_id BIGINT UNSIGNED NOT NULL,
  purchased_at DATETIME NOT NULL,
  expires_at DATETIME NULL,
  status ENUM('active','used','expired','cancelled') NOT NULL DEFAULT 'active',
  paid_amount DECIMAL(12,2) NOT NULL,
  membership_id BIGINT UNSIGNED NULL,
  financial_transaction_id BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_customer_package(tenant_id,customer_id,status),
  UNIQUE KEY uq_cp_financial_transaction(financial_transaction_id),
  INDEX idx_cp_membership(membership_id),
  CONSTRAINT fk_cp_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_cp_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  CONSTRAINT fk_cp_package FOREIGN KEY(package_id) REFERENCES service_packages(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS customer_package_usage (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  customer_package_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NULL,
  quantity INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_package_usage_appointment(customer_package_id,service_id,appointment_id),
  CONSTRAINT fk_cpu_cp FOREIGN KEY(customer_package_id) REFERENCES customer_packages(id) ON DELETE CASCADE,
  CONSTRAINT fk_cpu_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE RESTRICT,
  CONSTRAINT fk_cpu_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS customer_memberships (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  package_id BIGINT UNSIGNED NOT NULL,
  cycle ENUM('monthly','quarterly') NOT NULL DEFAULT 'monthly',
  recurring_amount DECIMAL(12,2) NOT NULL,
  status ENUM('active','paused','cancelled') NOT NULL DEFAULT 'active',
  started_at DATE NOT NULL,
  next_due_at DATE NOT NULL,
  last_billed_at DATE NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_membership_due(tenant_id,status,next_due_at),
  CONSTRAINT fk_cm_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_cm_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  CONSTRAINT fk_cm_package FOREIGN KEY(package_id) REFERENCES service_packages(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_loyalty_settings (
  tenant_id BIGINT UNSIGNED PRIMARY KEY,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  points_per_currency DECIMAL(8,2) NOT NULL DEFAULT 1,
  reward_points INT UNSIGNED NOT NULL DEFAULT 100,
  reward_value DECIMAL(10,2) NOT NULL DEFAULT 10,
  referral_points INT UNSIGNED NOT NULL DEFAULT 50,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_tls_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS loyalty_accounts (
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  points INT NOT NULL DEFAULT 0,
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(tenant_id,customer_id),
  CONSTRAINT fk_la_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS loyalty_transactions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  type ENUM('earn','redeem','adjust','reverse') NOT NULL,
  points INT NOT NULL,
  source_type VARCHAR(40) NULL,
  source_id BIGINT UNSIGNED NULL,
  note VARCHAR(255) NULL,
  user_id BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_lt_customer(tenant_id,customer_id,created_at),
  CONSTRAINT fk_lt_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS loyalty_rewards (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  points_spent INT UNSIGNED NOT NULL,
  reward_value DECIMAL(10,2) NOT NULL,
  status ENUM('available','redeemed','cancelled') NOT NULL DEFAULT 'available',
  issued_at DATETIME NOT NULL,
  redeemed_at DATETIME NULL,
  redeemed_by BIGINT UNSIGNED NULL,
  INDEX idx_lr_customer(tenant_id,customer_id,status),
  CONSTRAINT fk_lr_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS loyalty_referrals (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  referrer_customer_id BIGINT UNSIGNED NOT NULL,
  referred_customer_id BIGINT UNSIGNED NOT NULL,
  status ENUM('pending','completed','cancelled') NOT NULL DEFAULT 'pending',
  reward_points INT UNSIGNED NOT NULL,
  completed_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_referral_referred(tenant_id,referred_customer_id),
  INDEX idx_referral_referrer(tenant_id,referrer_customer_id,status),
  CONSTRAINT fk_ref_referrer FOREIGN KEY(referrer_customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  CONSTRAINT fk_ref_referred FOREIGN KEY(referred_customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS waitlist_entries (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NULL,
  preferred_date DATE NULL,
  period ENUM('any','morning','afternoon','evening') NOT NULL DEFAULT 'any',
  status ENUM('waiting','matched','booked','cancelled','expired') NOT NULL DEFAULT 'waiting',
  notes VARCHAR(255) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  last_notified_at DATETIME NULL,
  INDEX idx_waitlist_match(tenant_id,status,service_id,professional_id,preferred_date),
  CONSTRAINT fk_waitlist_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  CONSTRAINT fk_waitlist_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE,
  CONSTRAINT fk_waitlist_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_domains (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  domain VARCHAR(190) NOT NULL,
  status ENUM('pending','verified','failed','disabled') NOT NULL DEFAULT 'pending',
  verification_token VARCHAR(64) NOT NULL,
  verified_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_tenant_domain(domain),
  INDEX idx_tenant_domain(tenant_id,status),
  CONSTRAINT fk_td_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO modules(slug,name,active) VALUES
('packages','Pacotes e mensalidades',1),
('loyalty','Fidelidade',1),
('waitlist','Lista de espera inteligente',1),
('custom_domain','Domínio personalizado',1);

INSERT IGNORE INTO permissions(slug,name) VALUES
('agenda.blocks.manage','Gerenciar bloqueios e férias'),
('agenda.settings.manage','Configurar regras da agenda'),
('finance.categories.manage','Gerenciar categorias financeiras'),
('finance.cash.manage','Gerenciar caixa'),
('commissions.view','Visualizar comissões'),
('commissions.manage','Gerenciar comissões'),
('vehicles.view','Visualizar veículos'),
('vehicles.manage','Gerenciar veículos'),
('notifications.view','Visualizar notificações'),
('stock.adjust','Ajustar estoque'),
('packages.view','Visualizar pacotes'),
('packages.manage','Gerenciar pacotes'),
('loyalty.view','Visualizar fidelidade'),
('loyalty.manage','Gerenciar fidelidade'),
('waitlist.view','Visualizar lista de espera'),
('waitlist.manage','Gerenciar lista de espera'),
('domains.manage','Gerenciar domínio personalizado'),
('master.errors.view','Visualizar erros da aplicação'),
('master.automation.view','Visualizar automações globais');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN(
'agenda.blocks.manage','agenda.settings.manage','finance.categories.manage','finance.cash.manage','commissions.view','commissions.manage','vehicles.view','vehicles.manage','notifications.view','stock.adjust','packages.view','packages.manage','loyalty.view','loyalty.manage','waitlist.view','waitlist.manage','domains.manage')
WHERE r.slug IN('owner','manager');
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('agenda.blocks.manage','commissions.view','vehicles.view','notifications.view','waitlist.view') WHERE r.slug='professional';
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('vehicles.view','vehicles.manage','notifications.view','waitlist.view','waitlist.manage') WHERE r.slug='reception';

INSERT IGNORE INTO plan_modules(plan_id,module_id,enabled)
SELECT p.id,m.id,CASE
 WHEN p.slug='start' AND m.slug IN('loyalty') THEN 0
 WHEN p.slug='pro' AND m.slug IN('packages','loyalty','waitlist') THEN 1
 WHEN p.slug IN('business','health') AND m.slug IN('packages','loyalty','waitlist','custom_domain') THEN 1
 ELSE 0 END
FROM plans p JOIN modules m ON m.slug IN('packages','loyalty','waitlist','custom_domain');
