INSERT IGNORE INTO modules(slug,name,description,active,sort_order) VALUES
('sports_courts','Quadras e Esportes','Locação de quadras, modalidades, preços, reservas, recorrência e manutenção.',1,70);

INSERT IGNORE INTO permissions(slug,name) VALUES
('sports.view','Visualizar módulo de quadras'),
('sports.manage','Gerenciar quadras e configurações'),
('sports.reservations.manage','Gerenciar reservas de quadras'),
('sports.payments.manage','Confirmar pagamentos de quadras');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r CROSS JOIN permissions p
WHERE r.slug IN('owner','manager') AND p.slug LIKE 'sports.%';
INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN('sports.view','sports.reservations.manage')
WHERE r.slug='reception';

CREATE TABLE IF NOT EXISTS sports_settings(
 tenant_id BIGINT UNSIGNED PRIMARY KEY,
 public_enabled TINYINT(1) NOT NULL DEFAULT 1,
 default_slot_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 60,
 minimum_notice_minutes INT UNSIGNED NOT NULL DEFAULT 60,
 maximum_days_ahead SMALLINT UNSIGNED NOT NULL DEFAULT 90,
 cancellation_notice_minutes INT UNSIGNED NOT NULL DEFAULT 720,
 require_deposit TINYINT(1) NOT NULL DEFAULT 0,
 deposit_type ENUM('fixed','percent') NOT NULL DEFAULT 'percent',
 deposit_value DECIMAL(10,2) NOT NULL DEFAULT 0,
 pix_key VARCHAR(190) NULL,
 pix_holder VARCHAR(190) NULL,
 booking_terms TEXT NULL,
 updated_at DATETIME NOT NULL,
 CONSTRAINT fk_sports_settings_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_modalities(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 tenant_id BIGINT UNSIGNED NOT NULL,
 name VARCHAR(120) NOT NULL,
 description VARCHAR(500) NULL,
 active TINYINT(1) NOT NULL DEFAULT 1,
 sort_order INT NOT NULL DEFAULT 0,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_sports_modality(tenant_id,name),
 CONSTRAINT fk_sports_modality_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_courts(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 tenant_id BIGINT UNSIGNED NOT NULL,
 unit_id BIGINT UNSIGNED NULL,
 name VARCHAR(150) NOT NULL,
 slug VARCHAR(170) NOT NULL,
 description TEXT NULL,
 photo_path VARCHAR(500) NULL,
 surface VARCHAR(100) NULL,
 indoor TINYINT(1) NOT NULL DEFAULT 0,
 lighting TINYINT(1) NOT NULL DEFAULT 0,
 capacity SMALLINT UNSIGNED NULL,
 minimum_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 60,
 maximum_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 180,
 interval_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 0,
 active TINYINT(1) NOT NULL DEFAULT 1,
 sort_order INT NOT NULL DEFAULT 0,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_sports_court_slug(tenant_id,slug),
 INDEX idx_sports_court_unit(tenant_id,unit_id,active),
 CONSTRAINT fk_sports_court_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_court_unit FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE SET NULL
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_court_modalities(
 court_id BIGINT UNSIGNED NOT NULL,
 modality_id BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY(court_id,modality_id),
 CONSTRAINT fk_scm_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE CASCADE,
 CONSTRAINT fk_scm_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE CASCADE
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_court_hours(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 tenant_id BIGINT UNSIGNED NOT NULL,
 court_id BIGINT UNSIGNED NOT NULL,
 weekday TINYINT UNSIGNED NOT NULL,
 start_time TIME NOT NULL,
 end_time TIME NOT NULL,
 active TINYINT(1) NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_sports_hours(court_id,weekday,start_time,end_time),
 INDEX idx_sports_hours_lookup(court_id,weekday,active),
 CONSTRAINT fk_sports_hours_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_hours_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE CASCADE
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_price_rules(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 tenant_id BIGINT UNSIGNED NOT NULL,
 court_id BIGINT UNSIGNED NOT NULL,
 modality_id BIGINT UNSIGNED NULL,
 weekday TINYINT UNSIGNED NULL,
 start_time TIME NULL,
 end_time TIME NULL,
 price_per_hour DECIMAL(10,2) NOT NULL,
 priority SMALLINT NOT NULL DEFAULT 0,
 active TINYINT(1) NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 INDEX idx_sports_price_lookup(court_id,active,weekday,priority),
 CONSTRAINT fk_sports_price_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_price_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_price_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE CASCADE
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_court_blocks(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 tenant_id BIGINT UNSIGNED NOT NULL,
 court_id BIGINT UNSIGNED NOT NULL,
 starts_at DATETIME NOT NULL,
 ends_at DATETIME NOT NULL,
 reason VARCHAR(300) NULL,
 status ENUM('active','cancelled') NOT NULL DEFAULT 'active',
 created_by BIGINT UNSIGNED NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 INDEX idx_sports_blocks(court_id,status,starts_at,ends_at),
 CONSTRAINT fk_sports_block_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_block_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_block_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_reservations(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 public_id CHAR(32) NOT NULL,
 tenant_id BIGINT UNSIGNED NOT NULL,
 court_id BIGINT UNSIGNED NOT NULL,
 modality_id BIGINT UNSIGNED NULL,
 customer_id BIGINT UNSIGNED NULL,
 customer_name VARCHAR(160) NOT NULL,
 customer_phone VARCHAR(30) NOT NULL,
 customer_email VARCHAR(190) NULL,
 starts_at DATETIME NOT NULL,
 ends_at DATETIME NOT NULL,
 duration_minutes SMALLINT UNSIGNED NOT NULL,
 price_per_hour DECIMAL(10,2) NOT NULL,
 total_amount DECIMAL(10,2) NOT NULL,
 deposit_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
 status ENUM('pending_payment','confirmed','completed','cancelled','no_show') NOT NULL DEFAULT 'confirmed',
 payment_method ENUM('pix','onsite') NOT NULL DEFAULT 'onsite',
 payment_status ENUM('not_required','pending','paid','refunded','cancelled') NOT NULL DEFAULT 'not_required',
 manage_token_hash CHAR(64) NOT NULL,
 recurrence_group CHAR(32) NULL,
 source ENUM('public','internal','recurring') NOT NULL DEFAULT 'public',
 notes VARCHAR(1000) NULL,
 terms_accepted_at DATETIME NULL,
 confirmed_at DATETIME NULL,
 cancelled_at DATETIME NULL,
 created_by BIGINT UNSIGNED NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 UNIQUE KEY uq_sports_reservation_public(public_id),
 UNIQUE KEY uq_sports_reservation_token(manage_token_hash),
 INDEX idx_sports_reservation_calendar(court_id,status,starts_at,ends_at),
 INDEX idx_sports_reservation_tenant(tenant_id,status,starts_at),
 CONSTRAINT fk_sports_res_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_res_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE RESTRICT,
 CONSTRAINT fk_sports_res_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL,
 CONSTRAINT fk_sports_res_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
 CONSTRAINT fk_sports_res_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_reservation_history(
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 reservation_id BIGINT UNSIGNED NOT NULL,
 action VARCHAR(60) NOT NULL,
 old_status VARCHAR(40) NULL,
 new_status VARCHAR(40) NULL,
 notes VARCHAR(500) NULL,
 actor_user_id BIGINT UNSIGNED NULL,
 created_at DATETIME NOT NULL,
 INDEX idx_sports_res_history(reservation_id,created_at),
 CONSTRAINT fk_sports_history_res FOREIGN KEY(reservation_id) REFERENCES sports_reservations(id) ON DELETE CASCADE,
 CONSTRAINT fk_sports_history_user FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
)ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
