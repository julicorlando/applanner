CREATE TABLE IF NOT EXISTS marketing_referral_profiles (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 user_id BIGINT UNSIGNED NOT NULL,
 referral_code VARCHAR(32) NOT NULL,
 active TINYINT(1) NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_referral_profile_user(user_id),
 UNIQUE KEY uq_referral_profile_code(referral_code),
 CONSTRAINT fk_referral_profile_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS marketing_campaign_referrers (
 campaign_id BIGINT UNSIGNED PRIMARY KEY,
 referrer_user_id BIGINT UNSIGNED NOT NULL,
 created_at DATETIME NOT NULL,
 CONSTRAINT fk_campaign_referrer_campaign FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE CASCADE,
 CONSTRAINT fk_campaign_referrer_user FOREIGN KEY(referrer_user_id) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS marketing_referral_visits (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 referrer_user_id BIGINT UNSIGNED NOT NULL,
 campaign_id BIGINT UNSIGNED NULL,
 lead_id BIGINT UNSIGNED NULL,
 visit_token_hash CHAR(64) NOT NULL,
 ip_hash CHAR(64) NULL,
 user_agent VARCHAR(500) NULL,
 clicked_at DATETIME NOT NULL,
 converted_tenant_id BIGINT UNSIGNED NULL,
 converted_at DATETIME NULL,
 UNIQUE KEY uq_referral_visit_token(visit_token_hash),
 INDEX idx_referral_owner(referrer_user_id,clicked_at),
 INDEX idx_referral_conversion(converted_tenant_id,converted_at),
 CONSTRAINT fk_referral_visit_user FOREIGN KEY(referrer_user_id) REFERENCES users(id) ON DELETE RESTRICT,
 CONSTRAINT fk_referral_visit_campaign FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE SET NULL,
 CONSTRAINT fk_referral_visit_lead FOREIGN KEY(lead_id) REFERENCES marketing_leads(id) ON DELETE SET NULL,
 CONSTRAINT fk_referral_visit_tenant FOREIGN KEY(converted_tenant_id) REFERENCES tenants(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
