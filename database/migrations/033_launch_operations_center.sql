ALTER TABLE commercial_leads ADD COLUMN estimated_value DECIMAL(10,2) NULL AFTER business_type;
ALTER TABLE commercial_leads ADD COLUMN next_contact_at DATETIME NULL AFTER assigned_at;
ALTER TABLE commercial_leads ADD COLUMN contact_deadline_at DATETIME NULL AFTER next_contact_at;
ALTER TABLE commercial_leads ADD COLUMN loss_reason VARCHAR(255) NULL AFTER notes;

ALTER TABLE commercial_proposals ADD COLUMN approval_status ENUM('not_required','pending','approved','rejected') NOT NULL DEFAULT 'not_required' AFTER status;
ALTER TABLE commercial_proposals ADD COLUMN approved_by BIGINT UNSIGNED NULL AFTER approval_status;
ALTER TABLE commercial_proposals ADD COLUMN approved_at DATETIME NULL AFTER approved_by;
ALTER TABLE commercial_proposals ADD COLUMN accepted_at DATETIME NULL AFTER approved_at;
ALTER TABLE commercial_proposals ADD COLUMN accepted_ip_hash CHAR(64) NULL AFTER accepted_at;
ALTER TABLE commercial_proposals ADD CONSTRAINT fk_proposal_approver FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE commercial_commissions ADD COLUMN hold_until DATETIME NULL AFTER approved_at;

CREATE TABLE IF NOT EXISTS proposal_acceptances (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,proposal_id BIGINT UNSIGNED NOT NULL,document_hash CHAR(64) NOT NULL,
 proposal_snapshot_json JSON NOT NULL,ip_hash CHAR(64) NULL,user_agent VARCHAR(500) NULL,accepted_at DATETIME NOT NULL,
 UNIQUE KEY uq_proposal_acceptance(proposal_id),CONSTRAINT fk_pa_proposal FOREIGN KEY(proposal_id) REFERENCES commercial_proposals(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS homologation_runs (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,status ENUM('passed','warning','blocked') NOT NULL,
 score DECIMAL(5,2) NOT NULL,results_json JSON NOT NULL,executed_by BIGINT UNSIGNED NOT NULL,created_at DATETIME NOT NULL,
 INDEX idx_homologation_created(created_at),CONSTRAINT fk_hr_user FOREIGN KEY(executed_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS backup_verifications (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,backup_id BIGINT UNSIGNED NOT NULL,status ENUM('passed','failed') NOT NULL,
 checksum_sha256 CHAR(64) NULL,details VARCHAR(500) NULL,verified_by BIGINT UNSIGNED NOT NULL,verified_at DATETIME NOT NULL,
 INDEX idx_backup_verification(backup_id,verified_at),CONSTRAINT fk_bv_backup FOREIGN KEY(backup_id) REFERENCES backups(id) ON DELETE CASCADE,
 CONSTRAINT fk_bv_user FOREIGN KEY(verified_by) REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TRIGGER commercial_lead_notify_after_insert AFTER INSERT ON commercial_leads FOR EACH ROW INSERT INTO user_notifications(tenant_id,user_id,type,title,message,action_url,severity,created_at) SELECT NULL,u.id,'commercial_lead','Nova oportunidade comercial',CONCAT(NEW.name,' · ',NEW.business_type),'/comercial/oportunidades','info',NOW() FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id LEFT JOIN commercial_profiles cp ON cp.user_id=u.id WHERE u.tenant_id IS NULL AND u.status='active' AND (r.slug='master' OR (r.slug='commercial' AND cp.active=1));

CREATE TRIGGER commercial_proposal_approval_notify_after_insert AFTER INSERT ON commercial_proposals FOR EACH ROW INSERT INTO user_notifications(tenant_id,user_id,type,title,message,action_url,severity,created_at) SELECT NULL,u.id,'proposal_approval','Proposta aguardando aprovação',NEW.title,'/master/homologacao','warning',NOW() FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE u.tenant_id IS NULL AND u.status='active' AND r.slug='master' AND NEW.approval_status='pending';
