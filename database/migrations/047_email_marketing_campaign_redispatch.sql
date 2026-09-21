-- ApPlanner — Redisparo de campanhas preservando histórico
ALTER TABLE marketing_campaigns
  ADD COLUMN IF NOT EXISTS source_campaign_id BIGINT UNSIGNED NULL AFTER deleted_at,
  ADD COLUMN IF NOT EXISTS resend_number INT UNSIGNED NOT NULL DEFAULT 0 AFTER source_campaign_id,
  ADD COLUMN IF NOT EXISTS resent_at DATETIME NULL AFTER resend_number,
  ADD INDEX IF NOT EXISTS idx_marketing_campaign_resend (source_campaign_id,resend_number);
