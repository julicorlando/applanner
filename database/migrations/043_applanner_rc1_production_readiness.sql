-- ApPlanner RC1 Production Readiness
-- Corrige a fila de automações e adiciona diagnóstico persistente de jobs.
-- Não remove dados.

ALTER TABLE campaign_recipients
  MODIFY COLUMN status ENUM('queued','sent','delivered','clicked','converted','failed','opted_out','skipped')
  NOT NULL DEFAULT 'queued';

ALTER TABLE notifications
  MODIFY COLUMN status ENUM('queued','sent','failed','cancelled','skipped')
  NOT NULL DEFAULT 'queued';

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS last_error VARCHAR(500) NULL AFTER failed_at;

ALTER TABLE jobs
  ADD INDEX IF NOT EXISTS idx_jobs_stale (status, locked_at);
