-- ApPlanner — Gestão de campanhas de e-mail marketing
ALTER TABLE marketing_campaigns
  ADD COLUMN IF NOT EXISTS image_path VARCHAR(500) NULL AFTER body,
  ADD COLUMN IF NOT EXISTS image_url VARCHAR(700) NULL AFTER image_path,
  ADD COLUMN IF NOT EXISTS image_alt VARCHAR(190) NULL AFTER image_url,
  ADD COLUMN IF NOT EXISTS card_link_url VARCHAR(700) NULL AFTER image_alt,
  ADD COLUMN IF NOT EXISTS active TINYINT(1) NOT NULL DEFAULT 1 AFTER card_link_url,
  ADD COLUMN IF NOT EXISTS updated_at DATETIME NULL AFTER active,
  ADD COLUMN IF NOT EXISTS deleted_at DATETIME NULL AFTER updated_at,
  ADD INDEX IF NOT EXISTS idx_marketing_campaign_active (active,deleted_at,created_at);
