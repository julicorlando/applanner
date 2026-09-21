ALTER TABLE plans ADD COLUMN public_visible TINYINT(1) NOT NULL DEFAULT 1 AFTER active;
ALTER TABLE plans ADD COLUMN is_custom TINYINT(1) NOT NULL DEFAULT 0 AFTER public_visible;
ALTER TABLE plans ADD COLUMN created_by_user_id BIGINT UNSIGNED NULL AFTER is_custom;
ALTER TABLE plans ADD INDEX idx_plans_public(active,public_visible,sort_order);
ALTER TABLE plans ADD CONSTRAINT fk_plans_creator FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE commercial_proposals ADD COLUMN base_plan_id BIGINT UNSIGNED NULL AFTER plan_id;
ALTER TABLE commercial_proposals ADD COLUMN modules_json JSON NULL AFTER notes;
ALTER TABLE commercial_proposals ADD COLUMN features_json JSON NULL AFTER modules_json;
ALTER TABLE commercial_proposals ADD CONSTRAINT fk_commercial_proposal_base_plan FOREIGN KEY(base_plan_id) REFERENCES plans(id) ON DELETE SET NULL;

UPDATE plans SET public_visible=1 WHERE is_custom=0;
