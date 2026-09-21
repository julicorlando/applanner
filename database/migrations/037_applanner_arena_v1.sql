-- ApPlanner Arena V1
-- Incremental: preserves all existing sports data and module slug sports_courts.

UPDATE modules
SET name='Arena',
    description='Gestão de arenas, quadras e espaços esportivos: agenda, reservas, rachas, mensalistas, comandas, CRM e operação esportiva.',
    addon_sellable=1,
    sort_order=70,
    active=1
WHERE slug='sports_courts';

INSERT IGNORE INTO modules(slug,name,description,addon_monthly_price,addon_sellable,sort_order,active) VALUES
('sports_academy','Arena — Aulas e Escolinha','Turmas, alunos, responsáveis, presença, faltas e reposições vinculadas às quadras.',NULL,1,71,1),
('sports_tournaments','Arena — Torneios','Competições, equipes, partidas, classificação e mata-mata vinculados às quadras.',NULL,1,72,1),
('banking_integrations','Integrações Bancárias','Conexões autorizadas com provedores de pagamento, Pix, conciliação e webhooks por estabelecimento.',NULL,1,80,1);

INSERT IGNORE INTO permissions(slug,name) VALUES
('sports.agenda.view','Visualizar agenda visual da Arena'),
('sports.memberships.manage','Gerenciar mensalistas e horários fixos'),
('sports.games.manage','Gerenciar rachas e jogadores'),
('sports.waitlist.manage','Gerenciar lista de espera da Arena'),
('sports.commands.manage','Gerenciar comandas da Arena'),
('sports.reports.view','Visualizar relatórios da Arena'),
('sports.academy.manage','Gerenciar aulas e escolinha'),
('sports.tournaments.manage','Gerenciar torneios'),
('banking.view','Visualizar integrações bancárias'),
('banking.manage','Conectar e configurar provedores financeiros'),
('banking.transactions.view','Visualizar transações e conciliação'),
('banking.refunds.manage','Solicitar devoluções quando suportadas');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r CROSS JOIN permissions p
WHERE r.slug IN('owner','manager')
  AND (p.slug LIKE 'sports.%' OR p.slug LIKE 'banking.%');

INSERT IGNORE INTO role_permissions(role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p
  ON p.slug IN('sports.view','sports.agenda.view','sports.reservations.manage','sports.waitlist.manage','sports.commands.manage')
WHERE r.slug='reception';

-- Extensões de preço sem alterar a tabela legada: duração, feriado/data específica e período especial.
CREATE TABLE IF NOT EXISTS sports_price_rule_extensions (
  price_rule_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  rule_type ENUM('standard','holiday','special') NOT NULL DEFAULT 'standard',
  specific_date DATE NULL,
  valid_from DATE NULL,
  valid_to DATE NULL,
  minimum_duration_minutes SMALLINT UNSIGNED NULL,
  maximum_duration_minutes SMALLINT UNSIGNED NULL,
  label VARCHAR(160) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_spre_tenant_date(tenant_id,specific_date,valid_from,valid_to),
  CONSTRAINT fk_spre_rule FOREIGN KEY(price_rule_id) REFERENCES sports_price_rules(id) ON DELETE CASCADE,
  CONSTRAINT fk_spre_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dados financeiros detalhados da reserva sem alterar o ENUM legado de sports_reservations.
CREATE TABLE IF NOT EXISTS sports_reservation_finance (
  reservation_id BIGINT UNSIGNED PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  payment_state ENUM('not_required','pending','partial','paid','expired','cancelled','refunded','partially_refunded','failed') NOT NULL DEFAULT 'not_required',
  gross_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  deposit_due DECIMAL(12,2) NOT NULL DEFAULT 0,
  amount_paid DECIMAL(12,2) NOT NULL DEFAULT 0,
  amount_refunded DECIMAL(12,2) NOT NULL DEFAULT 0,
  fee_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  net_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  provider VARCHAR(40) NULL,
  external_reference VARCHAR(190) NULL,
  transaction_id VARCHAR(190) NULL,
  expires_at DATETIME NULL,
  paid_at DATETIME NULL,
  reconciled_at DATETIME NULL,
  updated_at DATETIME NOT NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_srf_provider_ref(tenant_id,provider,external_reference),
  INDEX idx_srf_tenant_state(tenant_id,payment_state,expires_at),
  CONSTRAINT fk_srf_reservation FOREIGN KEY(reservation_id) REFERENCES sports_reservations(id) ON DELETE CASCADE,
  CONSTRAINT fk_srf_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mensalistas / horários fixos.
CREATE TABLE IF NOT EXISTS sports_memberships (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  court_id BIGINT UNSIGNED NOT NULL,
  modality_id BIGINT UNSIGNED NULL,
  name VARCHAR(160) NOT NULL,
  frequency ENUM('weekly','biweekly','monthly') NOT NULL DEFAULT 'weekly',
  weekday TINYINT UNSIGNED NULL,
  day_of_month TINYINT UNSIGNED NULL,
  start_time TIME NOT NULL,
  duration_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 60,
  monthly_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  start_date DATE NOT NULL,
  end_date DATE NULL,
  next_generation_date DATE NULL,
  generate_days_ahead SMALLINT UNSIGNED NOT NULL DEFAULT 60,
  status ENUM('active','paused','cancelled') NOT NULL DEFAULT 'active',
  notes VARCHAR(1000) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_sports_memberships_tenant(tenant_id,status,next_generation_date),
  CONSTRAINT fk_sm_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sm_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
  CONSTRAINT fk_sm_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE RESTRICT,
  CONSTRAINT fk_sm_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL,
  CONSTRAINT fk_sm_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_membership_conflicts (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  membership_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  occurrence_date DATE NOT NULL,
  starts_at DATETIME NOT NULL,
  reason VARCHAR(300) NOT NULL,
  resolved_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_smc_occurrence(membership_id,starts_at),
  INDEX idx_smc_tenant(tenant_id,resolved_at,occurrence_date),
  CONSTRAINT fk_smc_membership FOREIGN KEY(membership_id) REFERENCES sports_memberships(id) ON DELETE CASCADE,
  CONSTRAINT fk_smc_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rachas / peladas.
CREATE TABLE IF NOT EXISTS sports_games (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  public_token CHAR(32) NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  reservation_id BIGINT UNSIGNED NULL,
  court_id BIGINT UNSIGNED NOT NULL,
  modality_id BIGINT UNSIGNED NULL,
  name VARCHAR(160) NOT NULL,
  starts_at DATETIME NOT NULL,
  ends_at DATETIME NOT NULL,
  total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  max_players SMALLINT UNSIGNED NOT NULL,
  minimum_players SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  split_payment TINYINT(1) NOT NULL DEFAULT 1,
  status ENUM('draft','open','confirmed','completed','cancelled') NOT NULL DEFAULT 'open',
  rules VARCHAR(1000) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_sports_game_token(public_token),
  INDEX idx_sports_games_tenant(tenant_id,status,starts_at),
  CONSTRAINT fk_sg_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sg_reservation FOREIGN KEY(reservation_id) REFERENCES sports_reservations(id) ON DELETE SET NULL,
  CONSTRAINT fk_sg_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE RESTRICT,
  CONSTRAINT fk_sg_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL,
  CONSTRAINT fk_sg_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_game_players (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  game_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NULL,
  name VARCHAR(160) NOT NULL,
  phone VARCHAR(30) NOT NULL,
  email VARCHAR(190) NULL,
  share_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  amount_paid DECIMAL(12,2) NOT NULL DEFAULT 0,
  participation_status ENUM('invited','confirmed','cancelled') NOT NULL DEFAULT 'confirmed',
  payment_status ENUM('pending','paid','cancelled','refunded') NOT NULL DEFAULT 'pending',
  manage_token_hash CHAR(64) NOT NULL,
  provider VARCHAR(40) NULL,
  provider_reference VARCHAR(190) NULL,
  confirmed_at DATETIME NULL,
  paid_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_sgp_token(manage_token_hash),
  INDEX idx_sgp_game(game_id,participation_status,payment_status),
  INDEX idx_sgp_tenant(tenant_id,phone),
  CONSTRAINT fk_sgp_game FOREIGN KEY(game_id) REFERENCES sports_games(id) ON DELETE CASCADE,
  CONSTRAINT fk_sgp_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sgp_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lista de espera específica de quadra (não reaproveita a waitlist de serviços/profissionais).
CREATE TABLE IF NOT EXISTS sports_waitlist (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  public_token CHAR(32) NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NULL,
  court_id BIGINT UNSIGNED NULL,
  modality_id BIGINT UNSIGNED NULL,
  customer_name VARCHAR(160) NOT NULL,
  customer_phone VARCHAR(30) NOT NULL,
  customer_email VARCHAR(190) NULL,
  preferred_date DATE NOT NULL,
  preferred_start TIME NULL,
  preferred_end TIME NULL,
  flexibility_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  duration_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 60,
  status ENUM('waiting','offered','converted','expired','cancelled') NOT NULL DEFAULT 'waiting',
  offer_expires_at DATETIME NULL,
  offered_at DATETIME NULL,
  converted_reservation_id BIGINT UNSIGNED NULL,
  notes VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_sports_waitlist_token(public_token),
  INDEX idx_sports_waitlist_match(tenant_id,status,preferred_date,court_id,modality_id),
  CONSTRAINT fk_swl_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_swl_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
  CONSTRAINT fk_swl_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE SET NULL,
  CONSTRAINT fk_swl_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL,
  CONSTRAINT fk_swl_reservation FOREIGN KEY(converted_reservation_id) REFERENCES sports_reservations(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Aulas / escolinha (módulo opcional).
CREATE TABLE IF NOT EXISTS sports_classes (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  court_id BIGINT UNSIGNED NOT NULL,
  modality_id BIGINT UNSIGNED NULL,
  teacher_name VARCHAR(160) NOT NULL,
  name VARCHAR(160) NOT NULL,
  level VARCHAR(100) NULL,
  weekday TINYINT UNSIGNED NOT NULL,
  start_time TIME NOT NULL,
  duration_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 60,
  capacity SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  monthly_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  status ENUM('active','paused','cancelled') NOT NULL DEFAULT 'active',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_sclasses_tenant(tenant_id,status,weekday,start_time),
  CONSTRAINT fk_sclass_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sclass_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE RESTRICT,
  CONSTRAINT fk_sclass_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_class_students (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  class_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  responsible_name VARCHAR(160) NULL,
  responsible_phone VARCHAR(30) NULL,
  status ENUM('active','paused','cancelled') NOT NULL DEFAULT 'active',
  joined_at DATE NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_scstudent(class_id,customer_id),
  CONSTRAINT fk_scs_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_scs_class FOREIGN KEY(class_id) REFERENCES sports_classes(id) ON DELETE CASCADE,
  CONSTRAINT fk_scs_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_class_attendance (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  class_id BIGINT UNSIGNED NOT NULL,
  student_id BIGINT UNSIGNED NOT NULL,
  class_date DATE NOT NULL,
  status ENUM('present','absent','excused','replacement') NOT NULL,
  notes VARCHAR(300) NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_scattendance(student_id,class_date),
  INDEX idx_scattendance_class(class_id,class_date),
  CONSTRAINT fk_sca_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sca_class FOREIGN KEY(class_id) REFERENCES sports_classes(id) ON DELETE CASCADE,
  CONSTRAINT fk_sca_student FOREIGN KEY(student_id) REFERENCES sports_class_students(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Torneios (módulo opcional).
CREATE TABLE IF NOT EXISTS sports_tournaments (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  modality_id BIGINT UNSIGNED NULL,
  name VARCHAR(160) NOT NULL,
  category VARCHAR(120) NULL,
  format ENUM('groups','knockout','groups_knockout') NOT NULL DEFAULT 'groups_knockout',
  registration_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  starts_on DATE NOT NULL,
  ends_on DATE NULL,
  status ENUM('draft','registration','running','completed','cancelled') NOT NULL DEFAULT 'draft',
  champion_team_id BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_stournament_tenant(tenant_id,status,starts_on),
  CONSTRAINT fk_stournament_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_stournament_modality FOREIGN KEY(modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_tournament_teams (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tournament_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(160) NOT NULL,
  captain_customer_id BIGINT UNSIGNED NULL,
  payment_status ENUM('pending','paid','cancelled','refunded') NOT NULL DEFAULT 'pending',
  amount_paid DECIMAL(12,2) NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_stteam_name(tournament_id,name),
  CONSTRAINT fk_stteam_tournament FOREIGN KEY(tournament_id) REFERENCES sports_tournaments(id) ON DELETE CASCADE,
  CONSTRAINT fk_stteam_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_stteam_captain FOREIGN KEY(captain_customer_id) REFERENCES customers(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_tournament_team_players (
  team_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  jersey_number SMALLINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  PRIMARY KEY(team_id,customer_id),
  CONSTRAINT fk_sttp_team FOREIGN KEY(team_id) REFERENCES sports_tournament_teams(id) ON DELETE CASCADE,
  CONSTRAINT fk_sttp_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
  CONSTRAINT fk_sttp_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_tournament_matches (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tournament_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  court_id BIGINT UNSIGNED NULL,
  home_team_id BIGINT UNSIGNED NULL,
  away_team_id BIGINT UNSIGNED NULL,
  phase VARCHAR(80) NOT NULL,
  group_name VARCHAR(40) NULL,
  starts_at DATETIME NULL,
  home_score SMALLINT NULL,
  away_score SMALLINT NULL,
  status ENUM('scheduled','running','completed','cancelled') NOT NULL DEFAULT 'scheduled',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  INDEX idx_stmatch_schedule(tenant_id,starts_at,court_id,status),
  CONSTRAINT fk_stmatch_tournament FOREIGN KEY(tournament_id) REFERENCES sports_tournaments(id) ON DELETE CASCADE,
  CONSTRAINT fk_stmatch_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_stmatch_court FOREIGN KEY(court_id) REFERENCES sports_courts(id) ON DELETE SET NULL,
  CONSTRAINT fk_stmatch_home FOREIGN KEY(home_team_id) REFERENCES sports_tournament_teams(id) ON DELETE SET NULL,
  CONSTRAINT fk_stmatch_away FOREIGN KEY(away_team_id) REFERENCES sports_tournament_teams(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Comandas da Arena: abertas durante a reserva e baixam estoque no fechamento.
CREATE TABLE IF NOT EXISTS sports_commands (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  public_id CHAR(32) NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  reservation_id BIGINT UNSIGNED NULL,
  customer_id BIGINT UNSIGNED NULL,
  status ENUM('open','closed','cancelled') NOT NULL DEFAULT 'open',
  subtotal DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount DECIMAL(12,2) NOT NULL DEFAULT 0,
  surcharge DECIMAL(12,2) NOT NULL DEFAULT 0,
  total DECIMAL(12,2) NOT NULL DEFAULT 0,
  payment_method VARCHAR(40) NULL,
  payment_status ENUM('pending','paid','partial','cancelled') NOT NULL DEFAULT 'pending',
  notes VARCHAR(500) NULL,
  opened_by BIGINT UNSIGNED NULL,
  closed_by BIGINT UNSIGNED NULL,
  opened_at DATETIME NOT NULL,
  closed_at DATETIME NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_scommand_public(public_id),
  INDEX idx_scommand_tenant(tenant_id,status,opened_at),
  CONSTRAINT fk_scommand_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_scommand_reservation FOREIGN KEY(reservation_id) REFERENCES sports_reservations(id) ON DELETE SET NULL,
  CONSTRAINT fk_scommand_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE SET NULL,
  CONSTRAINT fk_scommand_opened FOREIGN KEY(opened_by) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_scommand_closed FOREIGN KEY(closed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_command_items (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  command_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  product_id BIGINT UNSIGNED NULL,
  description VARCHAR(190) NOT NULL,
  quantity DECIMAL(12,3) NOT NULL,
  unit_price DECIMAL(12,2) NOT NULL,
  cost_snapshot DECIMAL(12,2) NOT NULL DEFAULT 0,
  total DECIMAL(12,2) NOT NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_scommand_items(command_id),
  CONSTRAINT fk_sci_command FOREIGN KEY(command_id) REFERENCES sports_commands(id) ON DELETE CASCADE,
  CONSTRAINT fk_sci_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_sci_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_command_stock_movements (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  command_id BIGINT UNSIGNED NOT NULL,
  product_id BIGINT UNSIGNED NOT NULL,
  quantity DECIMAL(12,3) NOT NULL,
  balance_after DECIMAL(12,3) NOT NULL,
  movement_type ENUM('command_close','command_reversal') NOT NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uq_scommand_stock(command_id,product_id,movement_type),
  CONSTRAINT fk_scsm_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_scsm_command FOREIGN KEY(command_id) REFERENCES sports_commands(id) ON DELETE CASCADE,
  CONSTRAINT fk_scsm_product FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- CRM esportivo materializado, recalculável pelo cron/dashboard.
CREATE TABLE IF NOT EXISTS sports_customer_metrics (
  tenant_id BIGINT UNSIGNED NOT NULL,
  customer_id BIGINT UNSIGNED NOT NULL,
  last_reservation_at DATETIME NULL,
  reservation_count INT UNSIGNED NOT NULL DEFAULT 0,
  cancellation_count INT UNSIGNED NOT NULL DEFAULT 0,
  no_show_count INT UNSIGNED NOT NULL DEFAULT 0,
  total_spent DECIMAL(14,2) NOT NULL DEFAULT 0,
  average_ticket DECIMAL(12,2) NOT NULL DEFAULT 0,
  favorite_court_id BIGINT UNSIGNED NULL,
  favorite_modality_id BIGINT UNSIGNED NULL,
  is_membership TINYINT(1) NOT NULL DEFAULT 0,
  game_count INT UNSIGNED NOT NULL DEFAULT 0,
  segment ENUM('new','recurring','vip','inactive','churn_risk') NOT NULL DEFAULT 'new',
  updated_at DATETIME NOT NULL,
  PRIMARY KEY(tenant_id,customer_id),
  INDEX idx_scm_segment(tenant_id,segment,last_reservation_at),
  CONSTRAINT fk_scm_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_scm_customer FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
  CONSTRAINT fk_scrm_favorite_court FOREIGN KEY(favorite_court_id) REFERENCES sports_courts(id) ON DELETE SET NULL,
  CONSTRAINT fk_scrm_favorite_modality FOREIGN KEY(favorite_modality_id) REFERENCES sports_modalities(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_automation_logs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  automation_key VARCHAR(80) NOT NULL,
  entity_type VARCHAR(60) NULL,
  entity_id BIGINT UNSIGNED NULL,
  channel VARCHAR(20) NULL,
  status ENUM('skipped','queued','sent','failed') NOT NULL,
  detail VARCHAR(500) NULL,
  created_at DATETIME NOT NULL,
  INDEX idx_sal_tenant(tenant_id,automation_key,created_at),
  CONSTRAINT fk_sal_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Integrações bancárias por tenant. Nunca guarda senha de internet banking.
CREATE TABLE IF NOT EXISTS tenant_payment_connections (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  provider VARCHAR(40) NOT NULL,
  display_name VARCHAR(120) NOT NULL,
  environment ENUM('sandbox','production') NOT NULL DEFAULT 'sandbox',
  auth_type ENUM('oauth','api_credentials','manual') NOT NULL DEFAULT 'api_credentials',
  credentials_encrypted LONGTEXT NULL,
  metadata_json LONGTEXT NULL,
  status ENUM('pending','connected','error','disabled') NOT NULL DEFAULT 'pending',
  last_tested_at DATETIME NULL,
  last_sync_at DATETIME NULL,
  last_error_code VARCHAR(80) NULL,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_tpc_provider(tenant_id,provider,environment),
  INDEX idx_tpc_tenant(tenant_id,status),
  CONSTRAINT fk_tpc_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_tpc_user FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_payment_transactions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tenant_id BIGINT UNSIGNED NOT NULL,
  connection_id BIGINT UNSIGNED NOT NULL,
  reference_type VARCHAR(40) NOT NULL,
  reference_id BIGINT UNSIGNED NOT NULL,
  external_reference VARCHAR(190) NOT NULL,
  provider_transaction_id VARCHAR(190) NULL,
  method VARCHAR(40) NOT NULL,
  gross_amount DECIMAL(12,2) NOT NULL,
  fee_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  net_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  status ENUM('created','pending','paid','failed','cancelled','expired','refunded','partially_refunded') NOT NULL DEFAULT 'created',
  pix_qr_code LONGTEXT NULL,
  pix_copy_paste LONGTEXT NULL,
  checkout_url VARCHAR(1000) NULL,
  expires_at DATETIME NULL,
  paid_at DATETIME NULL,
  reconciled_at DATETIME NULL,
  idempotency_key VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  UNIQUE KEY uq_tpt_idempotency(tenant_id,idempotency_key),
  UNIQUE KEY uq_tpt_external(connection_id,external_reference),
  INDEX idx_tpt_ref(tenant_id,reference_type,reference_id),
  INDEX idx_tpt_status(tenant_id,status,created_at),
  CONSTRAINT fk_tpt_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT fk_tpt_connection FOREIGN KEY(connection_id) REFERENCES tenant_payment_connections(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tenant_payment_webhook_events (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  connection_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  provider VARCHAR(40) NOT NULL,
  event_id VARCHAR(190) NOT NULL,
  payload_hash CHAR(64) NOT NULL,
  signature_valid TINYINT(1) NOT NULL DEFAULT 0,
  status ENUM('received','processed','ignored','failed') NOT NULL DEFAULT 'received',
  error_code VARCHAR(80) NULL,
  received_at DATETIME NOT NULL,
  processed_at DATETIME NULL,
  UNIQUE KEY uq_tpwe_event(connection_id,event_id),
  INDEX idx_tpwe_tenant(tenant_id,received_at),
  CONSTRAINT fk_tpwe_connection FOREIGN KEY(connection_id) REFERENCES tenant_payment_connections(id) ON DELETE CASCADE,
  CONSTRAINT fk_tpwe_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_arena_settings (
  tenant_id BIGINT UNSIGNED PRIMARY KEY,
  payment_deadline_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 10,
  waitlist_offer_minutes SMALLINT UNSIGNED NOT NULL DEFAULT 10,
  allow_waitlist TINYINT(1) NOT NULL DEFAULT 1,
  allow_games TINYINT(1) NOT NULL DEFAULT 1,
  dynamic_pricing_enabled TINYINT(1) NOT NULL DEFAULT 0,
  amenities_json LONGTEXT NULL,
  public_rules TEXT NULL,
  cancellation_policy TEXT NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_sas_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sports_membership_reservations (
  membership_id BIGINT UNSIGNED NOT NULL,
  reservation_id BIGINT UNSIGNED NOT NULL,
  tenant_id BIGINT UNSIGNED NOT NULL,
  occurrence_date DATE NOT NULL,
  created_at DATETIME NOT NULL,
  PRIMARY KEY(membership_id,reservation_id),
  UNIQUE KEY uq_smr_occurrence(membership_id,occurrence_date),
  CONSTRAINT fk_smr_membership FOREIGN KEY(membership_id) REFERENCES sports_memberships(id) ON DELETE CASCADE,
  CONSTRAINT fk_smr_reservation FOREIGN KEY(reservation_id) REFERENCES sports_reservations(id) ON DELETE CASCADE,
  CONSTRAINT fk_smr_tenant FOREIGN KEY(tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
