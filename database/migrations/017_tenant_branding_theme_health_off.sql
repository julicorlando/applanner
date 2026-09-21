ALTER TABLE tenants ADD COLUMN cover_path VARCHAR(255) NULL AFTER logo_path;
ALTER TABLE tenants ADD COLUMN menu_color CHAR(7) NOT NULL DEFAULT '#17213b' AFTER primary_color;
ALTER TABLE tenants ADD COLUMN menu_text_color CHAR(7) NOT NULL DEFAULT '#dce3f7' AFTER menu_color;
ALTER TABLE tenants ADD COLUMN background_color CHAR(7) NOT NULL DEFAULT '#f4f6fb' AFTER menu_text_color;
ALTER TABLE tenants ADD COLUMN text_color CHAR(7) NOT NULL DEFAULT '#17213b' AFTER background_color;
ALTER TABLE tenants ADD COLUMN font_family VARCHAR(40) NOT NULL DEFAULT 'Inter' AFTER text_color;
ALTER TABLE tenants ADD COLUMN font_size TINYINT UNSIGNED NOT NULL DEFAULT 15 AFTER font_family;
ALTER TABLE tenants ADD COLUMN accepted_payment_methods JSON NULL AFTER font_size;
ALTER TABLE tenants ADD COLUMN public_sections JSON NULL AFTER accepted_payment_methods;

ALTER TABLE units ADD COLUMN address_number VARCHAR(20) NULL AFTER address;
ALTER TABLE units ADD COLUMN address_complement VARCHAR(120) NULL AFTER address_number;
ALTER TABLE units ADD COLUMN district VARCHAR(100) NULL AFTER address_complement;
ALTER TABLE units ADD COLUMN city VARCHAR(100) NULL AFTER district;
ALTER TABLE units ADD COLUMN state CHAR(2) NULL AFTER city;
ALTER TABLE units ADD COLUMN postal_code VARCHAR(10) NULL AFTER state;
ALTER TABLE units ADD COLUMN whatsapp VARCHAR(30) NULL AFTER phone;
ALTER TABLE units ADD COLUMN email VARCHAR(190) NULL AFTER whatsapp;
ALTER TABLE units ADD COLUMN instagram VARCHAR(190) NULL AFTER email;
ALTER TABLE units ADD COLUMN facebook VARCHAR(255) NULL AFTER instagram;
ALTER TABLE units ADD COLUMN tiktok VARCHAR(190) NULL AFTER facebook;
ALTER TABLE units ADD COLUMN website VARCHAR(255) NULL AFTER tiktok;
ALTER TABLE units ADD COLUMN map_url VARCHAR(500) NULL AFTER website;
ALTER TABLE units ADD COLUMN amenities JSON NULL AFTER map_url;
ALTER TABLE units ADD COLUMN payment_methods JSON NULL AFTER amenities;
ALTER TABLE units ADD COLUMN public_notes VARCHAR(500) NULL AFTER payment_methods;
ALTER TABLE units ADD COLUMN is_primary TINYINT(1) NOT NULL DEFAULT 0 AFTER public_notes;

UPDATE units u JOIN (SELECT tenant_id,MIN(id) id FROM units GROUP BY tenant_id) first_unit ON first_unit.id=u.id SET u.is_primary=1;

UPDATE plans SET active=0,updated_at=NOW() WHERE slug='health';
UPDATE modules SET active=0 WHERE slug IN('medical_records','odontology');

CREATE TABLE IF NOT EXISTS data_import_jobs (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,tenant_id BIGINT UNSIGNED NOT NULL,user_id BIGINT UNSIGNED NOT NULL,source VARCHAR(40) NOT NULL DEFAULT 'appbarber',original_name VARCHAR(255) NOT NULL,status ENUM('processing','completed','failed') NOT NULL,summary_json JSON NULL,error_message VARCHAR(500) NULL,created_at DATETIME NOT NULL,completed_at DATETIME NULL,INDEX idx_import_tenant(tenant_id,created_at),CONSTRAINT fk_import_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS public_reviews (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,tenant_id BIGINT UNSIGNED NOT NULL,customer_name VARCHAR(120) NOT NULL,rating TINYINT UNSIGNED NOT NULL,comment VARCHAR(500) NOT NULL,active TINYINT(1) NOT NULL DEFAULT 1,created_at DATETIME NOT NULL,INDEX idx_public_review(tenant_id,active,created_at),CONSTRAINT fk_public_review_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
