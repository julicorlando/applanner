-- ApPlanner Barber V1 - operação completa para barbearias.
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS checked_in_at DATETIME NULL AFTER customer_confirmed_at;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_started_at DATETIME NULL AFTER checked_in_at;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS service_completed_at DATETIME NULL AFTER service_started_at;

CREATE TABLE IF NOT EXISTS professional_service_commissions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  commission_type ENUM('percent','fixed') NOT NULL DEFAULT 'percent',
  commission_value DECIMAL(10,2) NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_psc_rule(tenant_id,professional_id,service_id),
  INDEX idx_psc_prof(tenant_id,professional_id,active),
  CONSTRAINT fk_barber_psc_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_psc_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_psc_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS professional_compensation_models (
  professional_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  model ENUM('commission','chair_rent','daily_rent','hybrid') NOT NULL DEFAULT 'commission',
  monthly_rent DECIMAL(12,2) NOT NULL DEFAULT 0,
  daily_rent DECIMAL(12,2) NOT NULL DEFAULT 0,
  rent_due_day TINYINT UNSIGNED NOT NULL DEFAULT 5,
  service_commission_percent DECIMAL(5,2) NULL,
  notes VARCHAR(500) NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_barber_pcm_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_pcm_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS professional_goals (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  year SMALLINT UNSIGNED NOT NULL,
  month TINYINT UNSIGNED NOT NULL,
  revenue_target DECIMAL(12,2) NOT NULL DEFAULT 0,
  services_target INT UNSIGNED NOT NULL DEFAULT 0,
  products_target DECIMAL(12,2) NOT NULL DEFAULT 0,
  ticket_target DECIMAL(12,2) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_barber_goal(tenant_id,professional_id,year,month),
  CONSTRAINT fk_barber_goal_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_goal_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS barber_commands (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NULL,
  customer_id BIGINT UNSIGNED NULL,
  professional_id BIGINT UNSIGNED NULL,
  status ENUM('open','closed','cancelled') NOT NULL DEFAULT 'open',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  surcharge_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  tip_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  tip_professional_id BIGINT UNSIGNED NULL,
  total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  notes VARCHAR(500) NULL,
  opened_by BIGINT UNSIGNED NOT NULL,
  opened_at DATETIME NOT NULL,
  closed_by BIGINT UNSIGNED NULL,
  closed_at DATETIME NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_barber_command_appointment(tenant_id,appointment_id),
  INDEX idx_barber_command_status(tenant_id,status,opened_at),
  CONSTRAINT fk_barber_cmd_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_cmd_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_cmd_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_cmd_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_cmd_tip_prof FOREIGN KEY(tip_professional_id) REFERENCES professionals(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_cmd_open_user FOREIGN KEY(opened_by) REFERENCES users(id),
  CONSTRAINT fk_barber_cmd_close_user FOREIGN KEY(closed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS barber_command_items (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  command_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  item_type ENUM('service','product','manual') NOT NULL,
  service_id BIGINT UNSIGNED NULL,
  product_id BIGINT UNSIGNED NULL,
  professional_id BIGINT UNSIGNED NULL,
  description VARCHAR(190) NOT NULL,
  quantity DECIMAL(12,3) NOT NULL DEFAULT 1,
  unit_price DECIMAL(12,2) NOT NULL,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  total_amount DECIMAL(12,2) NOT NULL,
  cost_snapshot DECIMAL(12,2) NOT NULL DEFAULT 0,
  commission_amount_snapshot DECIMAL(12,2) NULL,
  is_primary_service TINYINT(1) NOT NULL DEFAULT 0,
  covered_by_package TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  INDEX idx_barber_ci_command(command_id,item_type),
  CONSTRAINT fk_barber_ci_command FOREIGN KEY(command_id) REFERENCES barber_commands(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_ci_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_ci_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_ci_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_ci_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS barber_command_payments (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  command_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  method VARCHAR(40) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  received_at DATETIME NOT NULL,
  INDEX idx_barber_cp_command(command_id,received_at),
  CONSTRAINT fk_barber_cp_command FOREIGN KEY(command_id) REFERENCES barber_commands(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_cp_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_cp_user FOREIGN KEY(user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS barber_queue_entries (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NULL,
  customer_name VARCHAR(150) NOT NULL,
  customer_phone VARCHAR(32) NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  preferred_professional_id BIGINT UNSIGNED NULL,
  assigned_professional_id BIGINT UNSIGNED NULL,
  appointment_id BIGINT UNSIGNED NULL,
  status ENUM('waiting','called','in_service','completed','cancelled','no_show') NOT NULL DEFAULT 'waiting',
  priority SMALLINT NOT NULL DEFAULT 0,
  notes VARCHAR(255) NULL,
  joined_at DATETIME NOT NULL,
  called_at DATETIME NULL,
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_barber_queue(tenant_id,status,priority,joined_at),
  CONSTRAINT fk_barber_queue_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_queue_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_queue_service FOREIGN KEY(service_id) REFERENCES services(id),
  CONSTRAINT fk_barber_queue_pref_prof FOREIGN KEY(preferred_professional_id) REFERENCES professionals(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_queue_assigned_prof FOREIGN KEY(assigned_professional_id) REFERENCES professionals(id) ON DELETE SET NULL,
  CONSTRAINT fk_barber_queue_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Infraestrutura genérica de assinatura recorrente do cliente final.
CREATE TABLE IF NOT EXISTS tenant_recurring_subscriptions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  connection_id BIGINT UNSIGNED NOT NULL,
  reference_type VARCHAR(40) NOT NULL,
  reference_id BIGINT UNSIGNED NOT NULL,
  external_reference VARCHAR(190) NOT NULL,
  provider_subscription_id VARCHAR(190) NULL,
  amount DECIMAL(12,2) NOT NULL,
  cycle_months TINYINT UNSIGNED NOT NULL DEFAULT 1,
  status ENUM('pending','authorized','paused','cancelled','error') NOT NULL DEFAULT 'pending',
  checkout_url VARCHAR(1000) NULL,
  idempotency_key VARCHAR(100) NOT NULL,
  last_payment_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_trs_idempotency(tenant_id,idempotency_key),
  UNIQUE KEY uq_trs_provider(connection_id,provider_subscription_id),
  INDEX idx_trs_ref(tenant_id,reference_type,reference_id),
  CONSTRAINT fk_barber_trs_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_barber_trs_connection FOREIGN KEY(connection_id) REFERENCES tenant_payment_connections(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE customer_memberships ADD COLUMN IF NOT EXISTS billing_mode ENUM('manual','provider') NOT NULL DEFAULT 'manual' AFTER recurring_amount;
ALTER TABLE customer_memberships ADD COLUMN IF NOT EXISTS provider_status VARCHAR(40) NULL AFTER billing_mode;
ALTER TABLE customer_memberships ADD COLUMN IF NOT EXISTS provider_subscription_id VARCHAR(190) NULL AFTER provider_status;
ALTER TABLE customer_memberships ADD COLUMN IF NOT EXISTS provider_checkout_url VARCHAR(1000) NULL AFTER provider_subscription_id;

ALTER TABLE professional_commissions MODIFY COLUMN source_type ENUM('service','product','command_service','command_product','tip') NOT NULL;
ALTER TABLE product_stock_movements MODIFY COLUMN type ENUM('sale','sale_reversal','adjustment','entry','command','command_reversal') NOT NULL;

INSERT IGNORE INTO permissions(slug,name) VALUES
('barber.commands.view','Visualizar comandas da barbearia'),
('barber.commands.manage','Gerenciar comandas da barbearia'),
('barber.queue.view','Visualizar fila e encaixes'),
('barber.queue.manage','Gerenciar fila e encaixes'),
('barber.goals.view','Visualizar metas da equipe'),
('barber.goals.manage','Gerenciar metas da equipe'),
('barber.compensation.manage','Gerenciar comissão e aluguel de cadeira');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('barber.commands.view','barber.commands.manage','barber.queue.view','barber.queue.manage','barber.goals.view','barber.goals.manage','barber.compensation.manage')
WHERE r.slug IN('owner','manager');
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('barber.commands.view','barber.commands.manage','barber.queue.view','barber.queue.manage','barber.goals.view')
WHERE r.slug='professional';
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('barber.commands.view','barber.commands.manage','barber.queue.view','barber.queue.manage')
WHERE r.slug='reception';
