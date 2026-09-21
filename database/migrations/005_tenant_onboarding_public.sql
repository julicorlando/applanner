ALTER TABLE tenants ADD COLUMN description TEXT NULL AFTER phone;
ALTER TABLE tenants ADD COLUMN logo_path VARCHAR(255) NULL AFTER description;
ALTER TABLE tenants ADD COLUMN primary_color CHAR(7) NOT NULL DEFAULT '#2563eb' AFTER logo_path;
ALTER TABLE tenants ADD COLUMN public_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER primary_color;
ALTER TABLE tenants ADD COLUMN onboarding_step TINYINT UNSIGNED NOT NULL DEFAULT 1 AFTER public_enabled;
ALTER TABLE tenants ADD COLUMN deleted_at DATETIME NULL AFTER updated_at;

CREATE TABLE IF NOT EXISTS units (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,tenant_id BIGINT UNSIGNED NOT NULL,name VARCHAR(150) NOT NULL,
 address VARCHAR(255) NULL,phone VARCHAR(32) NULL,active TINYINT(1) NOT NULL DEFAULT 1,created_at DATETIME NOT NULL,updated_at DATETIME NOT NULL,
 INDEX idx_unit_tenant(tenant_id,active),CONSTRAINT fk_unit_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE professionals ADD COLUMN unit_id BIGINT UNSIGNED NULL AFTER tenant_id;
ALTER TABLE professionals ADD CONSTRAINT fk_prof_unit FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS terms_acceptances (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,tenant_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,
 terms_version VARCHAR(30) NOT NULL,ip_address VARCHAR(64) NULL,accepted_at DATETIME NOT NULL,
 INDEX idx_terms_tenant(tenant_id,accepted_at),CONSTRAINT fk_terms_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id),CONSTRAINT fk_terms_user FOREIGN KEY(user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
