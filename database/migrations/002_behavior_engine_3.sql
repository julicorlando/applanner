ALTER TABLE behavior_profiles ADD COLUMN median_interval_days DECIMAL(8,2) NULL AFTER avg_interval_days;
ALTER TABLE behavior_profiles ADD COLUMN std_deviation_days DECIMAL(8,2) NULL AFTER median_interval_days;
ALTER TABLE behavior_profiles ADD COLUMN intervals_json JSON NULL AFTER visits_count;

CREATE TABLE IF NOT EXISTS behavior_service_profiles (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL, service_id BIGINT UNSIGNED NOT NULL,
  avg_interval_days DECIMAL(8,2) NULL, median_interval_days DECIMAL(8,2) NULL,
  std_deviation_days DECIMAL(8,2) NULL, last_visit_at DATETIME NULL, next_expected_date DATE NULL,
  confidence_score TINYINT UNSIGNED NOT NULL DEFAULT 0, visits_count INT UNSIGNED NOT NULL DEFAULT 0,
  intervals_json JSON NULL, updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_behavior_service (tenant_id,customer_id,service_id),
  INDEX idx_behavior_service_next (tenant_id,next_expected_date,confidence_score),
  CONSTRAINT fk_bsp_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_bsp_customer FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  CONSTRAINT fk_bsp_service FOREIGN KEY (service_id) REFERENCES services(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
