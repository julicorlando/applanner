INSERT IGNORE INTO roles(slug,name) VALUES('commercial','Comercial');

CREATE TABLE IF NOT EXISTS commercial_profiles (
 user_id BIGINT UNSIGNED PRIMARY KEY,
 commission_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
 max_discount_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
 active TINYINT(1) NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 CONSTRAINT fk_commercial_profile_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS commercial_proposals (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 commercial_user_id BIGINT UNSIGNED NOT NULL,
 plan_id BIGINT UNSIGNED NOT NULL,
 title VARCHAR(160) NOT NULL,
 customer_name VARCHAR(160) NULL,
 customer_email VARCHAR(190) NULL,
 discount_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
 final_price DECIMAL(10,2) NOT NULL,
 notes TEXT NULL,
 public_token CHAR(32) NOT NULL,
 status ENUM('draft','sent','viewed','converted','expired','cancelled') NOT NULL DEFAULT 'draft',
 tenant_id BIGINT UNSIGNED NULL,
 expires_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_commercial_proposal_token(public_token),
 INDEX idx_commercial_proposal_owner(commercial_user_id,status,created_at),
 CONSTRAINT fk_commercial_proposal_user FOREIGN KEY(commercial_user_id) REFERENCES users(id) ON DELETE CASCADE,
 CONSTRAINT fk_commercial_proposal_plan FOREIGN KEY(plan_id) REFERENCES plans(id),
 CONSTRAINT fk_commercial_proposal_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS commercial_commissions (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 commercial_user_id BIGINT UNSIGNED NOT NULL,
 tenant_id BIGINT UNSIGNED NOT NULL,
 payment_id BIGINT UNSIGNED NULL,
 base_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
 commission_percent DECIMAL(5,2) NOT NULL DEFAULT 0,
 commission_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
 status ENUM('projected','approved','reversed','paid') NOT NULL DEFAULT 'projected',
 approved_at DATETIME NULL,
 reversed_at DATETIME NULL,
 paid_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_commercial_commission_tenant(commercial_user_id,tenant_id),
 INDEX idx_commercial_commission_status(status,created_at),
 CONSTRAINT fk_commercial_commission_user FOREIGN KEY(commercial_user_id) REFERENCES users(id) ON DELETE RESTRICT,
 CONSTRAINT fk_commercial_commission_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_commercial_commission_payment FOREIGN KEY(payment_id) REFERENCES payments(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
