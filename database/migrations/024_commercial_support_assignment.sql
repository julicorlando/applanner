ALTER TABLE commercial_profiles
  ADD COLUMN support_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER active;

ALTER TABLE support_tickets
  ADD INDEX idx_support_assignee_status(assigned_to,status);
