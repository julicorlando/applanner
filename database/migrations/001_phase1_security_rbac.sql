CREATE TABLE IF NOT EXISTS permissions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  slug VARCHAR(120) NOT NULL UNIQUE,
  name VARCHAR(150) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS role_permissions (
  role_id BIGINT UNSIGNED NOT NULL,
  permission_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_rp_role FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
  CONSTRAINT fk_rp_permission FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO permissions (slug,name) VALUES
('dashboard.view','Visualizar dashboard'),('customers.view','Visualizar clientes'),('customers.create','Criar clientes'),
('services.view','Visualizar serviços'),('services.create','Criar serviços'),('agenda.view','Visualizar agenda'),
('agenda.create','Criar agendamentos'),('agenda.edit','Alterar agendamentos');

INSERT IGNORE INTO role_permissions (role_id,permission_id)
SELECT r.id,p.id FROM roles r CROSS JOIN permissions p WHERE r.slug IN ('owner','manager');

INSERT IGNORE INTO role_permissions (role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN ('dashboard.view','customers.view','customers.create','services.view','agenda.view','agenda.create','agenda.edit')
WHERE r.slug='reception';

INSERT IGNORE INTO role_permissions (role_id,permission_id)
SELECT r.id,p.id FROM roles r JOIN permissions p ON p.slug IN ('dashboard.view','customers.view','services.view','agenda.view','agenda.edit')
WHERE r.slug='professional';

CREATE TABLE IF NOT EXISTS login_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, user_id BIGINT UNSIGNED NULL, email VARCHAR(190) NOT NULL,
  successful TINYINT(1) NOT NULL, ip_address VARCHAR(64) NULL, user_agent VARCHAR(500) NULL, created_at DATETIME NOT NULL,
  INDEX idx_login_user_created (user_id,created_at), INDEX idx_login_email_created (email,created_at),
  CONSTRAINT fk_login_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
