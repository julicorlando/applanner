<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
require $root . '/app/Core/bootstrap.php';

use App\Core\Database;

$pdo = Database::connection();

function cut(?string $s, int $n=180): string {
    $s = trim((string)$s);
    return mb_strlen($s) > $n ? mb_substr($s,0,$n).'…' : $s;
}

$rc1At = null;
try {
    $q = $pdo->prepare("SELECT executed_at FROM migrations WHERE migration=:m ORDER BY id DESC LIMIT 1");
    $q->execute(['m'=>'043_applanner_rc1_production_readiness.sql']);
    $rc1At = $q->fetchColumn() ?: null;
} catch (Throwable $e) {
    fwrite(STDERR, "[ERRO] Não foi possível ler migration 043: ".$e->getMessage()."\n");
    exit(1);
}

echo "APPLANNER RC1 - SAÚDE DA FILA\n";
echo "==============================\n";
echo "Migration 043: ".($rc1At ?: 'sem timestamp')."\n\n";

$sql = "SELECT id,tenant_id,type,status,attempts,created_at,updated_at,failed_at,last_error
        FROM jobs
        WHERE status='failed'
        ORDER BY COALESCE(failed_at,updated_at,created_at),id";
$rows = $pdo->query($sql)->fetchAll(PDO::FETCH_ASSOC) ?: [];

$historical = [];
$current = [];
foreach ($rows as $r) {
    $when = $r['failed_at'] ?: ($r['updated_at'] ?: $r['created_at']);
    if ($rc1At && $when && strtotime($when) < strtotime((string)$rc1At)) $historical[] = $r;
    else $current[] = $r;
}

echo "Falhas históricas pré-RC1: ".count($historical)."\n";
foreach ($historical as $r) {
    echo "  [HIST] job={$r['id']} tenant=".($r['tenant_id'] ?? '-')
        ." type={$r['type']} attempts={$r['attempts']}"
        ." failed=".($r['failed_at'] ?: ($r['updated_at'] ?: $r['created_at']))
        ." error=".cut($r['last_error'] ?: 'sem diagnóstico histórico')."\n";
}

echo "\nFalhas pós-RC1: ".count($current)."\n";
foreach ($current as $r) {
    echo "  [ATUAL] job={$r['id']} tenant=".($r['tenant_id'] ?? '-')
        ." type={$r['type']} attempts={$r['attempts']}"
        ." failed=".($r['failed_at'] ?: ($r['updated_at'] ?: $r['created_at']))
        ." error=".cut($r['last_error'] ?: 'sem diagnóstico')."\n";
}

$stale = (int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='processing' AND locked_at<DATE_SUB(NOW(),INTERVAL 15 MINUTE)")->fetchColumn();
echo "\nJobs travados >15min: {$stale}\n";

if ($current) {
    echo "\nNO-GO FILA: existem falhas posteriores ao RC1.\n";
    exit(2);
}
if ($stale) {
    echo "\nNO-GO FILA: existem jobs travados.\n";
    exit(2);
}
echo "\nGO FILA: nenhuma falha nova após o RC1.\n";
exit(0);
