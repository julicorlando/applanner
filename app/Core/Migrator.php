<?php
namespace App\Core;

use PDO;

final class Migrator
{
    public static function run(PDO $pdo, string $directory): void
    {
        $pdo->exec("CREATE TABLE IF NOT EXISTS migrations (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, migration VARCHAR(190) NOT NULL UNIQUE, batch INT UNSIGNED NOT NULL, executed_at DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");
        $applied = array_flip($pdo->query('SELECT migration FROM migrations')->fetchAll(PDO::FETCH_COLUMN));
        $batch = (int)$pdo->query('SELECT COALESCE(MAX(batch),0)+1 FROM migrations')->fetchColumn();
        $files = glob(rtrim($directory, '/\\') . '/*.sql') ?: [];
        sort($files, SORT_STRING);
        foreach ($files as $file) {
            $name = basename($file);
            if (isset($applied[$name])) continue;
            $sql = file_get_contents($file);
            if ($sql === false) throw new \RuntimeException("Não foi possível ler a migration {$name}.");
            $pdo->beginTransaction();
            try {
                $pdo->exec($sql);
                $stmt = $pdo->prepare('INSERT INTO migrations (migration,batch,executed_at) VALUES (:migration,:batch,NOW())');
                $stmt->execute(['migration' => $name, 'batch' => $batch]);
                if ($pdo->inTransaction()) $pdo->commit();
            } catch (\Throwable $e) {
                if ($pdo->inTransaction()) $pdo->rollBack();
                throw $e;
            }
        }
    }
}
