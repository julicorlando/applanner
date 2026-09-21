CREATE TABLE IF NOT EXISTS two_factor_trusted_devices (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  selector CHAR(24) NOT NULL,
  validator_hash CHAR(64) NOT NULL,
  session_version INT UNSIGNED NOT NULL,
  device_label VARCHAR(120) NULL,
  user_agent VARCHAR(500) NULL,
  ip_address VARCHAR(64) NULL,
  last_used_at DATETIME NULL,
  expires_at DATETIME NOT NULL,
  revoked_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_2ftd_selector (selector),
  INDEX idx_2ftd_user_active (user_id, revoked_at, expires_at),
  INDEX idx_2ftd_expiry (expires_at, revoked_at),
  CONSTRAINT fk_2ftd_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
