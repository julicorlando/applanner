<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$payload = $root . '/patches/applanner-rc1-go/payload';
$errors = [];
$ok = [];

$need = [
    'app/Core/bootstrap.php',
    'app/Core/Migrator.php',
    'app/Services/BackupService.php',
    'cron/worker.php',
    'cron/arena.php',
    'cron/barber.php',
    'cron/auto.php',
    'app/Views/billing/modules.php',
];
foreach ($need as $rel) {
    if (!is_file($root . '/' . $rel)) $errors[] = "Arquivo obrigatório ausente: {$rel}";
    else $ok[] = $rel;
}
if (!is_file($payload . '/database/migrations/043_applanner_rc1_production_readiness.sql')) {
    $errors[] = 'Payload RC1 incompleto: migration 043 ausente.';
}
if (PHP_VERSION_ID < 80200) $errors[] = 'PHP 8.2+ é obrigatório. Atual: ' . PHP_VERSION;

$checksumFile = dirname($payload) . '/SHA256SUMS.txt';
if (!is_file($checksumFile)) {
    $errors[] = 'Manifesto SHA256 do payload não encontrado.';
} else {
    foreach (file($checksumFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
        if (!preg_match('/^([a-f0-9]{64})  (.+)$/', trim($line), $m)) { $errors[]='Linha inválida no SHA256SUMS.'; continue; }
        $target=$payload.'/'.$m[2];
        if(!is_file($target)){$errors[]='Payload ausente: '.$m[2];continue;}
        $actual=hash_file('sha256',$target);
        if(!hash_equals($m[1],$actual))$errors[]='Checksum divergente: '.$m[2];
    }
}

if (!$errors) {
    require $root . '/app/Core/bootstrap.php';
    try {
        $pdo = \App\Core\Database::connection();
        $db = (string)$pdo->query('SELECT DATABASE()')->fetchColumn();
        foreach (['jobs','campaign_recipients','migrations','payment_gateways','backups','backup_verifications'] as $table) {
            $q = $pdo->prepare("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=:db AND table_name=:t");
            $q->execute(['db'=>$db,'t'=>$table]);
            if (!(int)$q->fetchColumn()) $errors[] = "Tabela obrigatória ausente: {$table}";
        }
        $applied = $pdo->query("SELECT migration FROM migrations")->fetchAll(PDO::FETCH_COLUMN) ?: [];
        foreach ([
            '037_applanner_arena_v1.sql',
            '038_applanner_arena_v2_complete.sql',
            '039_modules_merged_subscription.sql',
            '040_applanner_barber_v1.sql',
            '041_applanner_auto_v1.sql',
            '042_two_factor_trusted_devices.sql',
        ] as $m) {
            if (!in_array($m, $applied, true)) $errors[] = "Pré-requisito não aplicado: {$m}";
        }
    } catch (Throwable $e) {
        $errors[] = 'Banco/preflight: ' . $e->getMessage();
    }
}

echo "APPLANNER RC1 - PRE-FLIGHT\n";
echo "==========================\n";
echo "PHP: " . PHP_VERSION . "\n";
echo "Raiz: {$root}\n";
if ($errors) {
    foreach ($errors as $e) echo "[ERRO] {$e}\n";
    echo "\nPRE-FLIGHT: FALHOU. Nenhuma alteração foi feita pelo RC1.\n";
    exit(1);
}
echo "[OK] Estrutura, banco e migrations 037-042 encontrados.\n";
echo "[OK] Payload RC1 íntegro.\n";
echo "PRE-FLIGHT RC1: OK. Nenhuma alteração foi feita pelo RC1.\n";
