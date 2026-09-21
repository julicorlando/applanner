ALTER TABLE modules ADD COLUMN description VARCHAR(500) NULL AFTER name;
ALTER TABLE modules ADD COLUMN addon_monthly_price DECIMAL(10,2) NULL AFTER description;
ALTER TABLE modules ADD COLUMN addon_sellable TINYINT(1) NOT NULL DEFAULT 0 AFTER addon_monthly_price;
ALTER TABLE modules ADD COLUMN sort_order SMALLINT NOT NULL DEFAULT 0 AFTER addon_sellable;

UPDATE modules SET name='Inteligência de retorno' WHERE slug='behavior';
UPDATE modules SET name='Prontuários' WHERE slug='medical_records';
UPDATE modules SET name='Domínio personalizado' WHERE slug='custom_domain';
UPDATE modules SET name='Multiunidade' WHERE slug='multiunit';
UPDATE modules SET name='Produtos e vendas' WHERE slug='products';
UPDATE modules SET name='Controle de estoque' WHERE slug='stock';
UPDATE modules SET name='Financeiro do estabelecimento' WHERE slug='finance';

CREATE TABLE IF NOT EXISTS legal_documents (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  type ENUM('terms','privacy') NOT NULL,
  version VARCHAR(30) NOT NULL,
  title VARCHAR(190) NOT NULL,
  content LONGTEXT NOT NULL,
  status ENUM('draft','published','archived') NOT NULL DEFAULT 'draft',
  published_at DATETIME NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_legal_type_version(type,version),
  INDEX idx_legal_current(type,status,published_at),
  CONSTRAINT fk_legal_created_by FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS legal_acceptances (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  document_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  ip_address VARCHAR(64) NULL,
  user_agent VARCHAR(500) NULL,
  accepted_at DATETIME NOT NULL,
  UNIQUE KEY uq_legal_acceptance_user_document(user_id,document_id),
  INDEX idx_legal_acceptance_tenant(tenant_id,accepted_at),
  CONSTRAINT fk_legal_acceptance_document FOREIGN KEY(document_id) REFERENCES legal_documents(id),
  CONSTRAINT fk_legal_acceptance_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE SET NULL,
  CONSTRAINT fk_legal_acceptance_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS module_requests (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  public_id CHAR(32) NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  module_id BIGINT UNSIGNED NOT NULL,
  requested_by BIGINT UNSIGNED NOT NULL,
  quoted_monthly_price DECIMAL(10,2) NOT NULL,
  status ENUM('pending','approved','awaiting_payment','active','payment_failed','rejected','cancelled') NOT NULL DEFAULT 'pending',
  tenant_note VARCHAR(500) NULL,
  master_note VARCHAR(500) NULL,
  reviewed_by BIGINT UNSIGNED NULL,
  reviewed_at DATETIME NULL,
  provider_reference VARCHAR(190) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_module_request_public(public_id),
  INDEX idx_module_request_tenant(tenant_id,status,created_at),
  INDEX idx_module_request_master(status,created_at),
  CONSTRAINT fk_module_request_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_module_request_module FOREIGN KEY(module_id) REFERENCES modules(id),
  CONSTRAINT fk_module_request_user FOREIGN KEY(requested_by) REFERENCES users(id),
  CONSTRAINT fk_module_request_reviewed FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_module_addons (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  module_id BIGINT UNSIGNED NOT NULL,
  module_request_id BIGINT UNSIGNED NULL,
  monthly_price DECIMAL(10,2) NOT NULL,
  status ENUM('pending','active','past_due','cancelled') NOT NULL DEFAULT 'pending',
  provider VARCHAR(40) NULL,
  provider_reference VARCHAR(190) NULL,
  started_at DATETIME NULL,
  next_billing_at DATETIME NULL,
  cancelled_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_tenant_module_addon(tenant_id,module_id),
  INDEX idx_tenant_module_addon_status(status,next_billing_at),
  CONSTRAINT fk_tma_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_tma_module FOREIGN KEY(module_id) REFERENCES modules(id),
  CONSTRAINT fk_tma_request FOREIGN KEY(module_request_id) REFERENCES module_requests(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE payments ADD COLUMN purpose VARCHAR(40) NOT NULL DEFAULT 'subscription' AFTER subscription_id;
ALTER TABLE payments ADD COLUMN reference_id BIGINT UNSIGNED NULL AFTER purpose;
ALTER TABLE payments ADD COLUMN environment VARCHAR(20) NOT NULL DEFAULT 'unknown' AFTER provider;
ALTER TABLE payments ADD INDEX idx_pay_purpose(purpose,reference_id,status);

CREATE TABLE IF NOT EXISTS platform_finance_categories (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(120) NOT NULL,
  type ENUM('income','expense','both') NOT NULL DEFAULT 'both',
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_platform_finance_category(name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS platform_financial_transactions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  category_id BIGINT UNSIGNED NULL,
  type ENUM('income','expense') NOT NULL,
  description VARCHAR(190) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  status ENUM('pending','paid','cancelled') NOT NULL DEFAULT 'pending',
  due_at DATE NULL,
  paid_at DATETIME NULL,
  notes VARCHAR(500) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_platform_finance_status(type,status,due_at),
  CONSTRAINT fk_pft_category FOREIGN KEY(category_id) REFERENCES platform_finance_categories(id) ON DELETE SET NULL,
  CONSTRAINT fk_pft_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO platform_finance_categories(name,type,active,created_at,updated_at) VALUES
('Infraestrutura','expense',1,NOW(),NOW()),
('Marketing','expense',1,NOW(),NOW()),
('Impostos e taxas','expense',1,NOW(),NOW()),
('Serviços profissionais','expense',1,NOW(),NOW()),
('Receitas diversas','income',1,NOW(),NOW());

INSERT IGNORE INTO permissions(slug,name) VALUES
('master.modules.manage','Gerenciar catálogo de módulos'),
('master.module_requests.manage','Gerenciar solicitações de módulos'),
('master.finance.manage','Gerenciar financeiro da plataforma'),
('master.legal.manage','Gerenciar documentos legais');
ALTER TABLE payment_gateways DROP INDEX provider;
ALTER TABLE payment_gateways ADD UNIQUE KEY uq_gateway_provider_environment(provider,environment);

UPDATE roles SET name='Administrador da plataforma' WHERE slug='master';
UPDATE plans SET name='Inicial' WHERE slug='start' AND name='Start';
UPDATE plans SET name='Profissional' WHERE slug='pro' AND name='Pro';
UPDATE plans SET name='Empresarial' WHERE slug='business' AND name='Business';
UPDATE plans SET name='Saúde' WHERE slug='health' AND name='Health';
