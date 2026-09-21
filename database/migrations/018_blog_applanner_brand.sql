CREATE TABLE IF NOT EXISTS blog_posts (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 title VARCHAR(180) NOT NULL,
 slug VARCHAR(190) NOT NULL UNIQUE,
 excerpt VARCHAR(320) NOT NULL,
 content LONGTEXT NOT NULL,
 cover_path VARCHAR(255) NULL,
 status ENUM('draft','published','archived') NOT NULL DEFAULT 'draft',
 featured TINYINT(1) NOT NULL DEFAULT 0,
 meta_title VARCHAR(180) NULL,
 meta_description VARCHAR(320) NULL,
 author_id BIGINT UNSIGNED NOT NULL,
 published_at DATETIME NULL,
 created_at DATETIME NOT NULL,
 updated_at DATETIME NOT NULL,
 INDEX idx_blog_public(status,published_at),
 CONSTRAINT fk_blog_author FOREIGN KEY(author_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
