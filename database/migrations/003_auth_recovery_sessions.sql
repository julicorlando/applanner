ALTER TABLE users ADD COLUMN email_verified_at DATETIME NULL AFTER last_login_at;
ALTER TABLE users ADD COLUMN session_version INT UNSIGNED NOT NULL DEFAULT 1 AFTER email_verified_at;

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE, expires_at DATETIME NOT NULL, used_at DATETIME NULL, created_at DATETIME NOT NULL,
  INDEX idx_reset_expiry (expires_at,used_at), CONSTRAINT fk_reset_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS jobs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, tenant_id BIGINT UNSIGNED NULL, type VARCHAR(100) NOT NULL,
  payload_encrypted LONGTEXT NOT NULL, status ENUM('queued','processing','completed','failed') NOT NULL DEFAULT 'queued',
  attempts TINYINT UNSIGNED NOT NULL DEFAULT 0, available_at DATETIME NOT NULL, locked_at DATETIME NULL,
  failed_at DATETIME NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  INDEX idx_jobs_queue (status,available_at), CONSTRAINT fk_job_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
