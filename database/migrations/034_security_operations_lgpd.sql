ALTER TABLE backups ADD COLUMN scope ENUM('database','database_uploads') NOT NULL DEFAULT 'database' AFTER type;
ALTER TABLE backups MODIFY COLUMN status ENUM('running','completed','failed','expired') NOT NULL;
ALTER TABLE backups ADD COLUMN checksum_sha256 CHAR(64) NULL AFTER size_bytes;
ALTER TABLE backups ADD COLUMN encrypted TINYINT(1) NOT NULL DEFAULT 0 AFTER checksum_sha256;
ALTER TABLE backups ADD COLUMN encryption_method VARCHAR(60) NULL AFTER encrypted;
ALTER TABLE backups ADD COLUMN expires_at DATETIME NULL AFTER completed_at;

ALTER TABLE backup_verifications ADD COLUMN verification_type ENUM('integrity','restore') NOT NULL DEFAULT 'integrity' AFTER backup_id;
ALTER TABLE backup_verifications ADD COLUMN restored_database VARCHAR(190) NULL AFTER details;
ALTER TABLE backup_verifications ADD COLUMN completed_at DATETIME NULL AFTER verified_at;

ALTER TABLE commercial_leads ADD COLUMN consent_granted TINYINT(1) NOT NULL DEFAULT 0 AFTER ip_hash;
ALTER TABLE commercial_leads ADD COLUMN consent_version VARCHAR(30) NULL AFTER consent_granted;
ALTER TABLE commercial_leads ADD COLUMN consent_purpose VARCHAR(255) NULL AFTER consent_version;
ALTER TABLE commercial_leads ADD COLUMN consent_at DATETIME NULL AFTER consent_purpose;
ALTER TABLE commercial_leads ADD COLUMN consent_user_agent VARCHAR(500) NULL AFTER consent_at;
ALTER TABLE commercial_leads ADD COLUMN retention_until DATETIME NULL AFTER consent_user_agent;
ALTER TABLE commercial_leads ADD COLUMN anonymized_at DATETIME NULL AFTER retention_until;
ALTER TABLE commercial_leads ADD COLUMN do_not_contact TINYINT(1) NOT NULL DEFAULT 0 AFTER anonymized_at;

CREATE TABLE IF NOT EXISTS platform_operation_settings (
 id TINYINT UNSIGNED NOT NULL PRIMARY KEY DEFAULT 1,
 backup_retention_days SMALLINT UNSIGNED NOT NULL DEFAULT 30,
 backup_include_uploads TINYINT(1) NOT NULL DEFAULT 1,
 backup_encrypt TINYINT(1) NOT NULL DEFAULT 1,
 backup_before_update TINYINT(1) NOT NULL DEFAULT 1,
 lead_retention_days SMALLINT UNSIGNED NOT NULL DEFAULT 730,
 critical_alert_email VARCHAR(190) NULL,
 critical_alerts_enabled TINYINT(1) NOT NULL DEFAULT 0,
 cron_stale_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 15,
 disk_min_free_mb INT UNSIGNED NOT NULL DEFAULT 1024,
 updated_by BIGINT UNSIGNED NULL,
 updated_at DATETIME NOT NULL,
 CONSTRAINT fk_operation_settings_user FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO platform_operation_settings(id,updated_at) VALUES(1,NOW());

CREATE TABLE IF NOT EXISTS operational_incidents (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 fingerprint CHAR(64) NOT NULL,
 category ENUM('application','webhook','job','cron','email','whatsapp','payment','disk','database','backup','privacy') NOT NULL,
 severity ENUM('info','warning','critical') NOT NULL,
 title VARCHAR(190) NOT NULL,
 details TEXT NULL,
 status ENUM('open','acknowledged','resolved') NOT NULL DEFAULT 'open',
 occurrence_count INT UNSIGNED NOT NULL DEFAULT 1,
 first_seen_at DATETIME NOT NULL,
 last_seen_at DATETIME NOT NULL,
 acknowledged_by BIGINT UNSIGNED NULL,
 acknowledged_at DATETIME NULL,
 resolved_by BIGINT UNSIGNED NULL,
 resolved_at DATETIME NULL,
 alert_sent_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_operational_incident_fingerprint(fingerprint),
 INDEX idx_operational_incident_status(status,severity,last_seen_at),
 CONSTRAINT fk_incident_ack_user FOREIGN KEY(acknowledged_by) REFERENCES users(id) ON DELETE SET NULL,
 CONSTRAINT fk_incident_res_user FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS lead_privacy_events (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 lead_id BIGINT UNSIGNED NOT NULL,
 action ENUM('created','viewed','exported','consent_updated','do_not_contact','anonymized','deleted') NOT NULL,
 actor_user_id BIGINT UNSIGNED NULL,
 ip_hash CHAR(64) NULL,
 metadata_json JSON NULL,
 created_at DATETIME NOT NULL,
 INDEX idx_lead_privacy_event(lead_id,created_at),
 CONSTRAINT fk_lpe_lead FOREIGN KEY(lead_id) REFERENCES commercial_leads(id) ON DELETE CASCADE,
 CONSTRAINT fk_lpe_user FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
