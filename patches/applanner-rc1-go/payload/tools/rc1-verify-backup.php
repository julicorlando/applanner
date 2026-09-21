<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require dirname(__DIR__) . '/app/Core/bootstrap.php';

use App\Core\Database;
use App\Services\BackupService;

$pdo = Database::connection();
$backup = $pdo->query("SELECT * FROM backups WHERE status='completed' ORDER BY id DESC LIMIT 1")->fetch();
if (!$backup) {
    fwrite(STDERR, "[ERRO] Nenhum backup concluído disponível para teste de restauração.\n");
    exit(1);
}

$userId = 0;
try {
    $q = $pdo->query("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.slug='master' ORDER BY u.id LIMIT 1");
    $userId = (int)$q->fetchColumn();
} catch (Throwable) {}
if ($userId <= 0) {
    $userId = (int)$pdo->query("SELECT id FROM users ORDER BY id LIMIT 1")->fetchColumn();
}
if ($userId <= 0) {
    fwrite(STDERR, "[ERRO] Nenhum usuário disponível para registrar a verificação do backup.\n");
    exit(1);
}

try {
    $result = (new BackupService())->testRestore($backup, $userId);
    echo "[OK] Backup #".(int)$backup['id']." restaurado em ambiente isolado: ".(int)($result['tables'] ?? 0)." tabela(s).\n";
    echo "[OK] A base temporária foi removida ao final do teste.\n";
    exit(0);
} catch (Throwable $e) {
    fwrite(STDERR, "[ERRO] Restauração isolada falhou: ".mb_substr($e->getMessage(),0,500)."\n");
    exit(1);
}
