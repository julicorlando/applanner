CREATE TABLE IF NOT EXISTS pix_charges (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 public_id CHAR(32) NOT NULL UNIQUE,
 tenant_id BIGINT UNSIGNED NOT NULL,
 subscription_id BIGINT UNSIGNED NOT NULL,
 checkout_session_id BIGINT UNSIGNED NOT NULL,
 payment_id BIGINT UNSIGNED NOT NULL,
 provider_order_id VARCHAR(190) NOT NULL,
 provider_payment_id VARCHAR(190) NULL,
 amount DECIMAL(10,2) NOT NULL,
 qr_code MEDIUMTEXT NULL,
 qr_code_base64 MEDIUMTEXT NULL,
 ticket_url VARCHAR(1000) NULL,
 status ENUM('pending','paid','expired','cancelled','failed') NOT NULL DEFAULT 'pending',
 expires_at DATETIME NOT NULL,
 paid_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 INDEX idx_pix_tenant_status(tenant_id,status,created_at),
 UNIQUE KEY uq_pix_order(provider_order_id),
 CONSTRAINT fk_pix_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id),
 CONSTRAINT fk_pix_subscription FOREIGN KEY(subscription_id) REFERENCES subscriptions(id),
 CONSTRAINT fk_pix_checkout FOREIGN KEY(checkout_session_id) REFERENCES checkout_sessions(id),
 CONSTRAINT fk_pix_payment FOREIGN KEY(payment_id) REFERENCES payments(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO settings(tenant_id,setting_key,setting_value,is_secret,updated_at)
SELECT NULL,'mercadopago.pix.enabled','1',0,NOW()
WHERE NOT EXISTS(SELECT 1 FROM settings WHERE tenant_id IS NULL AND setting_key='mercadopago.pix.enabled');
INSERT INTO settings(tenant_id,setting_key,setting_value,is_secret,updated_at)
SELECT NULL,'mercadopago.pix.expiration_hours','24',0,NOW()
WHERE NOT EXISTS(SELECT 1 FROM settings WHERE tenant_id IS NULL AND setting_key='mercadopago.pix.expiration_hours');
INSERT INTO settings(tenant_id,setting_key,setting_value,is_secret,updated_at)
SELECT NULL,'mercadopago.pix.discount_percent','0',0,NOW()
WHERE NOT EXISTS(SELECT 1 FROM settings WHERE tenant_id IS NULL AND setting_key='mercadopago.pix.discount_percent');
