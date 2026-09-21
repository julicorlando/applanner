-- V3 operational notifications: reception flow and subscription notices.
ALTER TABLE appointments MODIFY COLUMN status ENUM('pending','confirmed','waiting','in_progress','completed','cancelled','no_show') NOT NULL DEFAULT 'pending';

CREATE TABLE IF NOT EXISTS subscription_notice_log (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  subscription_id BIGINT UNSIGNED NOT NULL,
  notice_key VARCHAR(40) NOT NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_subscription_notice(subscription_id,notice_key),
  INDEX idx_subscription_notice_tenant(tenant_id,created_at),
  CONSTRAINT fk_subscription_notice_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_subscription_notice_subscription FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
