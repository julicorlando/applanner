-- ApPlanner: módulos adicionais incorporados ao valor da assinatura principal.
-- Migration incremental e não destrutiva.

ALTER TABLE subscriptions
  ADD COLUMN IF NOT EXISTS base_contracted_price DECIMAL(10,2) NULL AFTER contracted_price,
  ADD COLUMN IF NOT EXISTS addon_contracted_price DECIMAL(10,2) NOT NULL DEFAULT 0.00 AFTER base_contracted_price;

UPDATE subscriptions
SET base_contracted_price = contracted_price
WHERE base_contracted_price IS NULL;

ALTER TABLE tenant_module_addons
  ADD COLUMN IF NOT EXISTS billing_mode ENUM('separate','merged_subscription') NOT NULL DEFAULT 'separate' AFTER status;

ALTER TABLE checkout_sessions
  ADD COLUMN IF NOT EXISTS base_total DECIMAL(10,2) NULL AFTER total,
  ADD COLUMN IF NOT EXISTS addon_total DECIMAL(10,2) NOT NULL DEFAULT 0.00 AFTER base_total;

UPDATE checkout_sessions
SET base_total = total
WHERE base_total IS NULL;

CREATE TABLE IF NOT EXISTS subscription_module_adjustments (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  public_id CHAR(32) NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  subscription_id BIGINT UNSIGNED NOT NULL,
  module_request_id BIGINT UNSIGNED NULL,
  module_addon_id BIGINT UNSIGNED NULL,
  action ENUM('add','remove','consolidate') NOT NULL,
  previous_amount DECIMAL(10,2) NOT NULL,
  new_amount DECIMAL(10,2) NOT NULL,
  addon_monthly_price DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  provider VARCHAR(40) NULL,
  provider_reference VARCHAR(190) NULL,
  idempotency_key CHAR(64) NOT NULL,
  status ENUM('pending','applied','failed','sync_required') NOT NULL DEFAULT 'pending',
  error_code VARCHAR(120) NULL,
  created_by BIGINT UNSIGNED NULL,
  applied_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_sma_public(public_id),
  UNIQUE KEY uq_sma_idempotency(idempotency_key),
  INDEX idx_sma_tenant(tenant_id,status,created_at),
  INDEX idx_sma_subscription(subscription_id,created_at),
  CONSTRAINT fk_sma_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sma_subscription FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
  CONSTRAINT fk_sma_request FOREIGN KEY(module_request_id) REFERENCES module_requests(id) ON DELETE SET NULL,
  CONSTRAINT fk_sma_addon FOREIGN KEY(module_addon_id) REFERENCES tenant_module_addons(id) ON DELETE SET NULL,
  CONSTRAINT fk_sma_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
