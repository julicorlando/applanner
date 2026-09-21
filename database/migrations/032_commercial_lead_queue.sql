CREATE TABLE IF NOT EXISTS commercial_leads (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(160) NOT NULL,
 phone VARCHAR(30) NOT NULL,
 email VARCHAR(190) NOT NULL,
 business_type VARCHAR(100) NOT NULL,
 source VARCHAR(80) NOT NULL DEFAULT 'public_interest_form',
 status ENUM('new','in_service','contacted','qualified','converted','lost') NOT NULL DEFAULT 'new',
 assigned_to BIGINT UNSIGNED NULL,
 assigned_at DATETIME NULL,
 last_transferred_by BIGINT UNSIGNED NULL,
 last_transferred_at DATETIME NULL,
 notes TEXT NULL,
 ip_hash CHAR(64) NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 INDEX idx_commercial_leads_queue(status,assigned_to,created_at),
 CONSTRAINT fk_commercial_lead_assignee FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL,
 CONSTRAINT fk_commercial_lead_transfer FOREIGN KEY(last_transferred_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS commercial_lead_history (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 lead_id BIGINT UNSIGNED NOT NULL,
 from_user_id BIGINT UNSIGNED NULL,
 to_user_id BIGINT UNSIGNED NULL,
 action ENUM('created','claimed','transferred','status_changed') NOT NULL,
 notes VARCHAR(500) NULL,
 actor_user_id BIGINT UNSIGNED NULL,
 created_at DATETIME NOT NULL,
 INDEX idx_commercial_lead_history(lead_id,created_at),
 CONSTRAINT fk_clh_lead FOREIGN KEY(lead_id) REFERENCES commercial_leads(id) ON DELETE CASCADE,
 CONSTRAINT fk_clh_from FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE SET NULL,
 CONSTRAINT fk_clh_to FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE SET NULL,
 CONSTRAINT fk_clh_actor FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
