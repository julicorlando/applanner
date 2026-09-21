-- ApPlanner Auto V1: vertical especializada para lava-jato, estética automotiva e detailing.
-- Incremental: não remove nem recria estruturas existentes.

INSERT IGNORE INTO permissions(slug,name) VALUES
('auto.dashboard.view','Visualizar dashboard automotivo'),
('auto.bays.view','Visualizar boxes e vagas'),
('auto.bays.manage','Gerenciar boxes e vagas'),
('auto.jobs.view','Visualizar ordens automotivas'),
('auto.jobs.manage','Gerenciar ordens automotivas'),
('auto.inspection.manage','Gerenciar checklist e fotos automotivas'),
('auto.estimates.manage','Gerenciar orçamentos adicionais'),
('auto.commands.view','Visualizar comandas automotivas'),
('auto.commands.manage','Gerenciar comandas automotivas'),
('auto.crm.view','Visualizar CRM automotivo'),
('auto.crm.manage','Gerenciar CRM automotivo'),
('auto.reports.view','Visualizar relatórios automotivos'),
('auto.settings.manage','Configurar operação automotiva');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r CROSS JOIN permissions p
WHERE r.slug IN('owner','manager') AND p.slug LIKE 'auto.%';

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN(
'auto.dashboard.view','auto.bays.view','auto.jobs.view','auto.jobs.manage','auto.inspection.manage','auto.estimates.manage','auto.commands.view','auto.commands.manage','auto.crm.view','auto.reports.view'
) WHERE r.slug='reception';

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN(
'auto.dashboard.view','auto.bays.view','auto.jobs.view','auto.jobs.manage','auto.inspection.manage','auto.commands.view'
) WHERE r.slug='professional';

CREATE TABLE IF NOT EXISTS auto_settings (
  tenant_id BIGINT UNSIGNED PRIMARY KEY,
  public_enabled TINYINT(1) NOT NULL DEFAULT 1,
  slot_interval_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 30,
  default_buffer_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 10,
  require_checkin_photos TINYINT(1) NOT NULL DEFAULT 0,
  require_delivery_acceptance TINYINT(1) NOT NULL DEFAULT 0,
  crm_default_return_days SMALLINT UNSIGNED NOT NULL DEFAULT 30,
  terms_text TEXT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_auto_settings_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_vehicle_profiles (
  vehicle_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  vehicle_type VARCHAR(50) NULL,
  fuel_type VARCHAR(40) NULL,
  vin VARCHAR(40) NULL,
  current_odometer INT UNSIGNED NULL,
  size_class ENUM('compact','medium','large','pickup','motorcycle','other') NULL,
  preferred_notes VARCHAR(500) NULL,
  last_service_at DATETIME NULL,
  next_recommended_at DATE NULL,
  warranty_until DATE NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_auto_vehicle_profile_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_vehicle_profile_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  INDEX idx_auto_vehicle_return(tenant_id,next_recommended_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_service_bays (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  bay_type ENUM('box','vaga','elevador','lavagem','detailing','secagem','outro') NOT NULL DEFAULT 'box',
  capacity TINYINT UNSIGNED NOT NULL DEFAULT 1,
  buffer_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  notes VARCHAR(500) NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_auto_bay_name(tenant_id,name),
  INDEX idx_auto_bay_active(tenant_id,active,sort_order),
  CONSTRAINT fk_auto_bay_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_bay_hours (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  bay_id BIGINT UNSIGNED NOT NULL,
  weekday TINYINT UNSIGNED NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_auto_bay_hours(bay_id,weekday,start_time,end_time),
  INDEX idx_auto_bay_hours_day(tenant_id,bay_id,weekday,active),
  CONSTRAINT fk_auto_bay_hours_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_bay_hours_bay FOREIGN KEY(bay_id) REFERENCES auto_service_bays(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_bay_services (
  bay_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY(bay_id,service_id),
  CONSTRAINT fk_auto_bay_service_bay FOREIGN KEY(bay_id) REFERENCES auto_service_bays(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_bay_service_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_bay_service_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_jobs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NOT NULL,
  vehicle_id BIGINT UNSIGNED NOT NULL,
  bay_id BIGINT UNSIGNED NULL,
  assigned_professional_id BIGINT UNSIGNED NULL,
  status ENUM('scheduled','received','queue','preparation','in_service','drying','curing','ready','delivered','cancelled') NOT NULL DEFAULT 'scheduled',
  odometer_in INT UNSIGNED NULL,
  fuel_level ENUM('empty','quarter','half','three_quarters','full','unknown') NOT NULL DEFAULT 'unknown',
  keys_received TINYINT UNSIGNED NOT NULL DEFAULT 0,
  expected_ready_at DATETIME NULL,
  received_at DATETIME NULL,
  started_at DATETIME NULL,
  ready_at DATETIME NULL,
  delivered_at DATETIME NULL,
  internal_notes TEXT NULL,
  public_notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_auto_job_appointment(tenant_id,appointment_id),
  INDEX idx_auto_job_status(tenant_id,status,created_at),
  INDEX idx_auto_job_bay(tenant_id,bay_id,status),
  INDEX idx_auto_job_vehicle(tenant_id,vehicle_id,created_at),
  CONSTRAINT fk_auto_job_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE RESTRICT,
  CONSTRAINT fk_auto_job_bay FOREIGN KEY(bay_id) REFERENCES auto_service_bays(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_job_prof FOREIGN KEY(assigned_professional_id) REFERENCES professionals(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_job_status_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  old_status VARCHAR(40) NULL,
  new_status VARCHAR(40) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_job_history(job_id,created_at),
  CONSTRAINT fk_auto_job_history_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_history_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_history_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_job_inspection_items (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  phase ENUM('checkin','checkout') NOT NULL DEFAULT 'checkin',
  area VARCHAR(80) NOT NULL,
  item_label VARCHAR(120) NOT NULL,
  condition_status ENUM('ok','attention','damaged','not_checked') NOT NULL DEFAULT 'not_checked',
  notes VARCHAR(500) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_inspection(job_id,phase),
  CONSTRAINT fk_auto_inspection_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_inspection_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_inspection_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_job_photos (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  phase ENUM('before','damage','process','after','delivery') NOT NULL,
  file_path VARCHAR(255) NOT NULL,
  caption VARCHAR(190) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_job_photo(job_id,phase,created_at),
  CONSTRAINT fk_auto_photo_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_photo_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_photo_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_job_material_usage (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  product_id BIGINT UNSIGNED NOT NULL,
  quantity DECIMAL(10,3) NOT NULL,
  dilution VARCHAR(60) NULL,
  batch_lot VARCHAR(100) NULL,
  notes VARCHAR(500) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_job_material(job_id,product_id),
  CONSTRAINT fk_auto_job_material_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_material_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_material_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
  CONSTRAINT fk_auto_job_material_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_job_technical_details (
  job_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  return_days SMALLINT UNSIGNED NULL,
  warranty_days SMALLINT UNSIGNED NULL,
  quality_notes TEXT NULL,
  updated_by BIGINT UNSIGNED NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_auto_job_technical_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_technical_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_technical_user FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_estimates (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  public_token_hash CHAR(64) NOT NULL,
  public_token_encrypted TEXT NOT NULL,
  status ENUM('draft','sent','approved','rejected','expired','cancelled') NOT NULL DEFAULT 'draft',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  expires_at DATETIME NULL,
  sent_at DATETIME NULL,
  responded_at DATETIME NULL,
  customer_note VARCHAR(500) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_auto_estimate_token(public_token_hash),
  INDEX idx_auto_estimate_job(tenant_id,job_id,status),
  CONSTRAINT fk_auto_estimate_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_estimate_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_estimate_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_estimate_items (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  estimate_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NULL,
  product_id BIGINT UNSIGNED NULL,
  description VARCHAR(190) NOT NULL,
  quantity DECIMAL(10,3) NOT NULL DEFAULT 1,
  unit_price DECIMAL(12,2) NOT NULL,
  total_amount DECIMAL(12,2) NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_estimate_items(estimate_id),
  CONSTRAINT fk_auto_estimate_item_estimate FOREIGN KEY(estimate_id) REFERENCES auto_estimates(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_estimate_item_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_estimate_item_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_estimate_item_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_commands (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  vehicle_id BIGINT UNSIGNED NOT NULL,
  status ENUM('open','closed','cancelled') NOT NULL DEFAULT 'open',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  surcharge_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  opened_by BIGINT UNSIGNED NULL,
  opened_at DATETIME NOT NULL,
  closed_by BIGINT UNSIGNED NULL,
  closed_at DATETIME NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_auto_command_job(tenant_id,job_id),
  INDEX idx_auto_command_status(tenant_id,status,opened_at),
  CONSTRAINT fk_auto_command_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
  CONSTRAINT fk_auto_command_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE RESTRICT,
  CONSTRAINT fk_auto_command_open_user FOREIGN KEY(opened_by) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_command_close_user FOREIGN KEY(closed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_command_items (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  command_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  item_type ENUM('service','product','material','manual') NOT NULL,
  service_id BIGINT UNSIGNED NULL,
  product_id BIGINT UNSIGNED NULL,
  professional_id BIGINT UNSIGNED NULL,
  description VARCHAR(190) NOT NULL,
  quantity DECIMAL(10,3) NOT NULL DEFAULT 1,
  unit_price DECIMAL(12,2) NOT NULL,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  total_amount DECIMAL(12,2) NOT NULL,
  cost_snapshot DECIMAL(12,2) NULL,
  approved_estimate_id BIGINT UNSIGNED NULL,
  is_primary_service TINYINT(1) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_command_items(command_id),
  CONSTRAINT fk_auto_command_item_command FOREIGN KEY(command_id) REFERENCES auto_commands(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_item_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_item_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_command_item_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_command_item_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_command_item_estimate FOREIGN KEY(approved_estimate_id) REFERENCES auto_estimates(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_command_payments (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  command_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  payment_method ENUM('pix','dinheiro','credito','debito','outro') NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  provider VARCHAR(50) NULL,
  provider_reference VARCHAR(190) NULL,
  received_by BIGINT UNSIGNED NULL,
  received_at DATETIME NOT NULL,
  INDEX idx_auto_command_payment(command_id,received_at),
  CONSTRAINT fk_auto_command_payment_command FOREIGN KEY(command_id) REFERENCES auto_commands(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_payment_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_command_payment_user FOREIGN KEY(received_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_service_materials (
  tenant_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  product_id BIGINT UNSIGNED NOT NULL,
  quantity DECIMAL(10,3) NOT NULL,
  PRIMARY KEY(service_id,product_id),
  CONSTRAINT fk_auto_material_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_material_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_material_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_service_steps (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  service_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(120) NOT NULL,
  step_type ENUM('preparation','service','drying','curing','quality','delivery','other') NOT NULL DEFAULT 'service',
  expected_minutes SMALLINT UNSIGNED NULL,
  sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  INDEX idx_auto_service_steps(service_id,active,sort_order),
  CONSTRAINT fk_auto_service_step_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_service_step_service FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_job_steps (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  service_step_id BIGINT UNSIGNED NULL,
  name VARCHAR(120) NOT NULL,
  status ENUM('pending','in_progress','completed','skipped') NOT NULL DEFAULT 'pending',
  started_at DATETIME NULL,
  completed_at DATETIME NULL,
  professional_id BIGINT UNSIGNED NULL,
  notes VARCHAR(500) NULL,
  sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  INDEX idx_auto_job_steps(job_id,status,sort_order),
  CONSTRAINT fk_auto_job_step_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_step_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_job_step_template FOREIGN KEY(service_step_id) REFERENCES auto_service_steps(id) ON DELETE SET NULL,
  CONSTRAINT fk_auto_job_step_prof FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_vehicle_package_links (
  customer_package_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  vehicle_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_vehicle_package(tenant_id,vehicle_id),
  CONSTRAINT fk_auto_vehicle_package_cp FOREIGN KEY(customer_package_id) REFERENCES customer_packages(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_vehicle_package_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_vehicle_package_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_membership_vehicle_links (
  membership_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  vehicle_id BIGINT UNSIGNED NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_membership_vehicle(tenant_id,vehicle_id),
  CONSTRAINT fk_auto_membership_vehicle_membership FOREIGN KEY(membership_id) REFERENCES customer_memberships(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_membership_vehicle_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_membership_vehicle_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_vehicle_maintenance (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  vehicle_id BIGINT UNSIGNED NOT NULL,
  source_job_id BIGINT UNSIGNED NULL,
  title VARCHAR(150) NOT NULL,
  performed_at DATE NOT NULL,
  next_due_at DATE NULL,
  warranty_until DATE NULL,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_auto_maintenance_due(tenant_id,next_due_at),
  INDEX idx_auto_maintenance_vehicle(vehicle_id,performed_at),
  CONSTRAINT fk_auto_maintenance_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_maintenance_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_maintenance_job FOREIGN KEY(source_job_id) REFERENCES auto_jobs(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_delivery_terms (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  public_token_hash CHAR(64) NOT NULL,
  public_token_encrypted TEXT NOT NULL,
  terms_snapshot TEXT NOT NULL,
  accepted_name VARCHAR(150) NULL,
  accepted_ip VARCHAR(64) NULL,
  accepted_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_auto_delivery_job(job_id),
  UNIQUE KEY uq_auto_delivery_token(public_token_hash),
  CONSTRAINT fk_auto_delivery_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_delivery_job FOREIGN KEY(job_id) REFERENCES auto_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS auto_crm_events (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  vehicle_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  event_type ENUM('return_due','warranty_due','inactive','manual') NOT NULL,
  due_at DATE NOT NULL,
  status ENUM('pending','notified','done','cancelled') NOT NULL DEFAULT 'pending',
  channel VARCHAR(30) NULL,
  notified_at DATETIME NULL,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_auto_crm_event(tenant_id,vehicle_id,event_type,due_at),
  INDEX idx_auto_crm_due(tenant_id,status,due_at),
  CONSTRAINT fk_auto_crm_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_crm_vehicle FOREIGN KEY(vehicle_id) REFERENCES customer_vehicles(id) ON DELETE CASCADE,
  CONSTRAINT fk_auto_crm_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Amplia a fonte das comissões sem remover valores anteriores.
ALTER TABLE professional_commissions MODIFY COLUMN source_type ENUM('service','product','command_service','command_product','tip','auto_service','auto_product') NOT NULL;

-- Permite baixa de estoque pelas comandas automotivas mesmo quando o Barber V1 ainda não foi instalado.
ALTER TABLE product_stock_movements MODIFY COLUMN type ENUM('sale','sale_reversal','adjustment','entry','command','command_reversal') NOT NULL;
