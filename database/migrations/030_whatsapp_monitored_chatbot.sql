CREATE TABLE IF NOT EXISTS whatsapp_conversations (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, tenant_id BIGINT UNSIGNED NOT NULL, customer_id BIGINT UNSIGNED NULL,
 wa_id VARCHAR(32) NOT NULL, contact_name VARCHAR(150) NULL, status ENUM('bot','waiting_human','human','closed') NOT NULL DEFAULT 'bot',
 bot_state VARCHAR(60) NOT NULL DEFAULT 'welcome', assigned_to BIGINT UNSIGNED NULL, context_json JSON NULL,
 last_message_at DATETIME NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_wa_conversation(tenant_id,wa_id), INDEX idx_wa_inbox(tenant_id,status,last_message_at),
 CONSTRAINT fk_wac_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_wac_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
 CONSTRAINT fk_wac_assignee FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS whatsapp_messages (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, conversation_id BIGINT UNSIGNED NOT NULL, tenant_id BIGINT UNSIGNED NOT NULL,
 provider_message_id VARCHAR(190) NULL, direction ENUM('in','out') NOT NULL, sender_type ENUM('customer','bot','user','system') NOT NULL,
 user_id BIGINT UNSIGNED NULL, message_type VARCHAR(30) NOT NULL DEFAULT 'text', body TEXT NULL,
 status ENUM('received','queued','sent','delivered','read','failed') NOT NULL, error_message VARCHAR(500) NULL,
 created_at DATETIME NOT NULL, sent_at DATETIME NULL,
 UNIQUE KEY uq_wa_provider_message(provider_message_id), INDEX idx_wa_messages(conversation_id,id),
 CONSTRAINT fk_wam_conversation FOREIGN KEY(conversation_id) REFERENCES whatsapp_conversations(id) ON DELETE CASCADE,
 CONSTRAINT fk_wam_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_wam_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
