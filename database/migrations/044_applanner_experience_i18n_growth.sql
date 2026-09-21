-- ApPlanner Experience, i18n & Growth. Incremental and non-destructive.
ALTER TABLE users ADD COLUMN IF NOT EXISTS locale VARCHAR(10) NOT NULL DEFAULT 'pt_BR' AFTER status;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS default_locale VARCHAR(10) NOT NULL DEFAULT 'pt_BR' AFTER category;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_layout VARCHAR(24) NOT NULL DEFAULT 'editorial' AFTER public_sections;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_headline VARCHAR(120) NULL AFTER public_layout;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_subheadline VARCHAR(300) NULL AFTER public_headline;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_cta_label VARCHAR(60) NULL AFTER public_subheadline;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_announcement VARCHAR(160) NULL AFTER public_cta_label;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_accent_color VARCHAR(7) NULL AFTER public_announcement;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_section_order JSON NULL AFTER public_accent_color;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_seo_title VARCHAR(70) NULL AFTER public_section_order;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_seo_description VARCHAR(180) NULL AFTER public_seo_title;
ALTER TABLE tenants ADD COLUMN IF NOT EXISTS public_instagram VARCHAR(120) NULL AFTER public_seo_description;

CREATE TABLE IF NOT EXISTS cron_heartbeats (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 cron_key VARCHAR(80) NOT NULL,
 started_at DATETIME NOT NULL,
 finished_at DATETIME NULL,
 status ENUM('running','ok','warning','failed') NOT NULL DEFAULT 'running',
 duration_ms INT UNSIGNED NULL,
 details VARCHAR(500) NULL,
 host_name VARCHAR(190) NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_cron_heartbeat_run (cron_key,started_at),
 KEY idx_cron_health (cron_key,status,finished_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
