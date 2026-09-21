-- Growth, public editor, full public i18n and operational alerts.
-- Incremental: no destructive changes.
CREATE TABLE IF NOT EXISTS acquisition_events (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 session_key CHAR(40) NOT NULL,event_id CHAR(36) NOT NULL,event_name VARCHAR(50) NOT NULL,
 tenant_id BIGINT UNSIGNED NULL,user_id BIGINT UNSIGNED NULL,segment VARCHAR(40) NULL,
 source VARCHAR(100) NULL,medium VARCHAR(100) NULL,campaign VARCHAR(120) NULL,content VARCHAR(120) NULL,term VARCHAR(120) NULL,
 event_url VARCHAR(500) NULL,referrer VARCHAR(500) NULL,client_ip_hash CHAR(64) NULL,user_agent_hash CHAR(64) NULL,marketing_consent TINYINT(1) NOT NULL DEFAULT 0,
 value_amount DECIMAL(12,2) NULL,currency CHAR(3) NOT NULL DEFAULT 'BRL',created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_acquisition_event_id(event_id),KEY idx_acquisition_funnel(event_name,created_at),KEY idx_acquisition_campaign(campaign,created_at),KEY idx_acquisition_session(session_key,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meta_conversion_log (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,event_id CHAR(36) NOT NULL,event_name VARCHAR(50) NOT NULL,
 status ENUM('queued','sent','failed','skipped') NOT NULL DEFAULT 'queued',http_status SMALLINT NULL,response_excerpt VARCHAR(500) NULL,
 attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,sent_at DATETIME NULL,created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at DATETIME NULL,
 UNIQUE KEY uq_meta_event(event_id),KEY idx_meta_status(status,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS public_content_translations (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,tenant_id BIGINT UNSIGNED NOT NULL,locale VARCHAR(10) NOT NULL,content_key VARCHAR(80) NOT NULL,content_value TEXT NULL,updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_public_translation(tenant_id,locale,content_key),CONSTRAINT fk_public_translation_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cron_alert_log (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,alert_key VARCHAR(190) NOT NULL,channel VARCHAR(20) NOT NULL,status ENUM('sent','failed','skipped') NOT NULL,
 message VARCHAR(500) NOT NULL,error_message VARCHAR(500) NULL,created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY idx_cron_alert_dedupe(alert_key,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
