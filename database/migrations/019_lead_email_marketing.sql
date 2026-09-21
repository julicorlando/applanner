CREATE TABLE IF NOT EXISTS marketing_leads (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(160) NOT NULL,
 email VARCHAR(190) NOT NULL,
 status ENUM('active','unsubscribed','bounced') NOT NULL DEFAULT 'active',
 source ENUM('manual','list','csv') NOT NULL DEFAULT 'manual',
 unsubscribe_token CHAR(64) NOT NULL,
 consent_at DATETIME NULL,
 unsubscribed_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_marketing_lead_email(email),
 UNIQUE KEY uq_marketing_unsubscribe_token(unsubscribe_token),
 INDEX idx_marketing_lead_status(status,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS marketing_campaigns (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 subject VARCHAR(190) NOT NULL,
 body LONGTEXT NOT NULL,
 status ENUM('queued','sending','completed','cancelled') NOT NULL DEFAULT 'queued',
 total_count INT UNSIGNED NOT NULL DEFAULT 0,
 sent_count INT UNSIGNED NOT NULL DEFAULT 0,
 failed_count INT UNSIGNED NOT NULL DEFAULT 0,
 created_by BIGINT UNSIGNED NOT NULL,
 created_at DATETIME NOT NULL,
 queued_at DATETIME NULL,
 completed_at DATETIME NULL,
 INDEX idx_marketing_campaign_status(status,created_at),
 CONSTRAINT fk_marketing_campaign_user FOREIGN KEY(created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS marketing_deliveries (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 campaign_id BIGINT UNSIGNED NOT NULL,
 lead_id BIGINT UNSIGNED NOT NULL,
 status ENUM('queued','sent','failed','skipped') NOT NULL DEFAULT 'queued',
 error_message VARCHAR(500) NULL,
 sent_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_marketing_delivery(campaign_id,lead_id),
 INDEX idx_marketing_delivery_status(campaign_id,status),
 CONSTRAINT fk_marketing_delivery_campaign FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE CASCADE,
 CONSTRAINT fk_marketing_delivery_lead FOREIGN KEY(lead_id) REFERENCES marketing_leads(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
