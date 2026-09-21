ALTER TABLE users ADD COLUMN two_factor_last_step BIGINT NULL AFTER two_factor_enabled_at;
ALTER TABLE payments ADD UNIQUE KEY uq_payment_provider_ref(provider,provider_reference);
ALTER TABLE payments ADD COLUMN idempotency_key VARCHAR(100) NULL AFTER provider_reference;
ALTER TABLE payments ADD UNIQUE KEY uq_payment_idempotency(tenant_id,idempotency_key);
CREATE TABLE IF NOT EXISTS security_events(id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,tenant_id BIGINT UNSIGNED NULL,user_id BIGINT UNSIGNED NULL,event_type VARCHAR(80)NOT NULL,severity ENUM('low','medium','high','critical')NOT NULL,ip_address VARCHAR(64)NULL,user_agent VARCHAR(500)NULL,metadata_json JSON NULL,created_at DATETIME NOT NULL,INDEX idx_security_event(event_type,severity,created_at),INDEX idx_security_tenant(tenant_id,created_at))ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
