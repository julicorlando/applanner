-- Operationalize selectable modules and remove phantom plan features.
INSERT IGNORE INTO permissions(slug,name) VALUES
('units.view','Visualizar unidades'),
('units.manage','Gerenciar unidades'),
('medical_records.view','Visualizar prontuários autorizados'),
('medical_records.create','Registrar evolução/prontuário');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('units.view','units.manage')
WHERE r.slug IN('owner','manager');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('medical_records.view','medical_records.create')
WHERE r.slug='professional';

CREATE TABLE IF NOT EXISTS medical_record_entries (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  professional_id BIGINT UNSIGNED NOT NULL,
  appointment_id BIGINT UNSIGNED NULL,
  record_type ENUM('evolution','anamnesis','procedure','observation','follow_up') NOT NULL DEFAULT 'evolution',
  title VARCHAR(190) NOT NULL,
  content_encrypted TEXT NOT NULL,
  created_by BIGINT UNSIGNED NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_mre_tenant_customer(tenant_id,customer_id,created_at),
  INDEX idx_mre_professional(tenant_id,professional_id,created_at),
  CONSTRAINT fk_mre_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_mre_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
  CONSTRAINT fk_mre_professional FOREIGN KEY(professional_id) REFERENCES professionals(id) ON DELETE RESTRICT,
  CONSTRAINT fk_mre_appointment FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE SET NULL,
  CONSTRAINT fk_mre_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- These are not separate tenant-facing modules in the current release.
UPDATE modules SET active=0 WHERE slug IN('whatsapp','odontology','api');
