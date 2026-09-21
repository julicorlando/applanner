ALTER TABLE users ADD COLUMN two_factor_secret LONGTEXT NULL AFTER session_version;
ALTER TABLE users ADD COLUMN two_factor_enabled_at DATETIME NULL AFTER two_factor_secret;

CREATE TABLE IF NOT EXISTS two_factor_recovery_codes (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL,
  code_hash CHAR(64) NOT NULL, used_at DATETIME NULL, created_at DATETIME NOT NULL,
  UNIQUE KEY uq_recovery_code (user_id,code_hash), CONSTRAINT fk_recovery_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS email_verification_tokens (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE, expires_at DATETIME NOT NULL, used_at DATETIME NULL, created_at DATETIME NOT NULL,
  INDEX idx_verify_expiry (expires_at,used_at), CONSTRAINT fk_verify_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
