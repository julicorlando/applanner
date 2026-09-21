-- Product completion: professional availability, sellable master controls, support access and operational reporting.

CREATE TABLE IF NOT EXISTS professional_availability (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  weekday TINYINT UNSIGNED NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_prof_availability_day (professional_id, weekday),
  INDEX idx_prof_availability_tenant (tenant_id, professional_id, weekday, active),
  CONSTRAINT fk_pa_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_pa_prof FOREIGN KEY (professional_id) REFERENCES professionals(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE appointments ADD COLUMN service_price_snapshot DECIMAL(10,2) NULL AFTER service_id;
UPDATE appointments a JOIN services s ON s.id=a.service_id SET a.service_price_snapshot=s.price WHERE a.service_price_snapshot IS NULL;

ALTER TABLE support_tickets ADD COLUMN remote_access_allowed TINYINT(1) NOT NULL DEFAULT 0 AFTER assigned_to;
ALTER TABLE support_tickets ADD COLUMN remote_access_allowed_at DATETIME NULL AFTER remote_access_allowed;
ALTER TABLE support_tickets ADD COLUMN remote_access_revoked_at DATETIME NULL AFTER remote_access_allowed_at;
ALTER TABLE support_access_sessions ADD COLUMN impersonated_user_id BIGINT UNSIGNED NULL AFTER master_user_id;

CREATE TABLE IF NOT EXISTS platform_automation_log (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  event_type VARCHAR(60) NOT NULL,
  channel ENUM('email','whatsapp') NOT NULL,
  scheduled_for DATE NOT NULL,
  status ENUM('queued','sent','failed','skipped') NOT NULL DEFAULT 'queued',
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_platform_automation (tenant_id,customer_id,event_type,channel,scheduled_for),
  INDEX idx_platform_automation_tenant (tenant_id,scheduled_for,status),
  CONSTRAINT fk_pal_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_pal_customer FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO roles(slug,name) VALUES ('support','Suporte da Plataforma');
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('master.support.manage','master.support.impersonate','master.login_audit.view')
WHERE r.slug='support';

INSERT IGNORE INTO permissions(slug,name) VALUES
('reports.view','Visualizar relatórios'),
('professional.availability','Gerenciar própria disponibilidade'),
('professional.performance','Visualizar próprio desempenho');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('reports.view') WHERE r.slug IN('owner','manager');
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('professional.availability','professional.performance') WHERE r.slug='professional';

-- Existing plans receive sensible module defaults without forcing tenants to edit code.
INSERT IGNORE INTO plan_modules(plan_id,module_id,enabled)
SELECT p.id,m.id,
CASE
  WHEN p.slug='start' AND m.slug IN('products') THEN 1
  WHEN p.slug='pro' AND m.slug IN('products','stock','finance','behavior') THEN 1
  WHEN p.slug='business' AND m.slug IN('products','stock','finance','behavior','multiunit') THEN 1
  WHEN p.slug='health' AND m.slug IN('products','stock','finance','behavior','multiunit','medical_records','odontology') THEN 1
  ELSE 0
END
FROM plans p CROSS JOIN modules m;
