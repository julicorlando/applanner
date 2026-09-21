INSERT IGNORE INTO roles(slug,name) VALUES('support','Suporte da Plataforma'),('commercial','Comercial');

ALTER TABLE units ADD COLUMN latitude DECIMAL(10,7) NULL AFTER postal_code;
ALTER TABLE units ADD COLUMN longitude DECIMAL(10,7) NULL AFTER latitude;
ALTER TABLE units ADD COLUMN geocoded_at DATETIME NULL AFTER longitude;
ALTER TABLE units ADD INDEX idx_units_public_geo(active,latitude,longitude);
