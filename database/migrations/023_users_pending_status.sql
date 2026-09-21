ALTER TABLE users
  MODIFY COLUMN status ENUM('active','pending','blocked','inactive')
  NOT NULL DEFAULT 'active';
