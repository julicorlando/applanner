-- ApPlanner - E-mail Marketing com Card/Imagem
ALTER TABLE marketing_campaigns
  ADD COLUMN IF NOT EXISTS image_path VARCHAR(500) NULL AFTER body,
  ADD COLUMN IF NOT EXISTS image_url VARCHAR(700) NULL AFTER image_path,
  ADD COLUMN IF NOT EXISTS image_alt VARCHAR(190) NULL AFTER image_url,
  ADD COLUMN IF NOT EXISTS card_link_url VARCHAR(700) NULL AFTER image_alt;
