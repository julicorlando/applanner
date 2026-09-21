<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$payload = $root . '/patches/applanner-barber-v1/payload';
$dry = in_array('--dry-run', $argv, true);

$fail = static function (string $message): never {
    fwrite(STDERR, "[ERRO] {$message}\n");
    exit(1);
};
$run = static function (string $cmd, ?array &$out = null): int {
    $buffer = [];
    $code = 0;
    exec($cmd . ' 2>&1', $buffer, $code);
    if ($out !== null) $out = $buffer;
    return $code;
};
$copy = static function (string $src, string $dst): void {
    $dir = dirname($dst);
    if (!is_dir($dir) && !mkdir($dir, 0755, true) && !is_dir($dir)) {
        throw new RuntimeException('Falha ao criar diretório ' . $dir);
    }
    if (!copy($src, $dst)) throw new RuntimeException('Falha ao copiar ' . $dst);
};

$preflight = [];
$preflightCode = $run(
    escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($root . '/tools/preflight-barber-v1.php'),
    $preflight
);
echo implode("\n", $preflight) . "\n";
if ($preflightCode !== 0) $fail('Preflight falhou. Corrija os itens acima antes de instalar.');

$files = [];
if (!is_dir($payload)) $fail('Payload Barber V1 não encontrado.');
$it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload, FilesystemIterator::SKIP_DOTS));
foreach ($it as $file) {
    if (!$file->isFile()) continue;
    $rel = str_replace('\\', '/', substr($file->getPathname(), strlen($payload) + 1));
    $files[$rel] = $file->getPathname();
}
ksort($files);

if ($dry) {
    echo "\n[OK] DRY RUN: preflight e payload validados; banco e arquivos não foram alterados.\n";
    echo "DRY RUN: OK. Execute sem --dry-run para instalar.\n";
    exit(0);
}

$backupRoot = $root . '/storage/update-backups';
$backupDir = $backupRoot . '/barber-v1-' . date('Ymd-His');
if (!is_dir($backupDir) && !mkdir($backupDir, 0750, true) && !is_dir($backupDir)) {
    $fail('Não foi possível criar o backup em ' . $backupDir);
}

$manifest = [
    'patch' => 'PATCH_APPLANNER_BARBER_V1_COMPLETO',
    'created_at' => date(DATE_ATOM),
    'backup_dir' => $backupDir,
    'files' => [],
];

try {
    // Backup de tudo que o payload pode substituir/criar.
    foreach ($files as $rel => $src) {
        $dst = $root . '/' . $rel;
        $exists = is_file($dst);
        $manifest['files'][] = [
            'path' => $rel,
            'existed' => $exists,
            'sha256_before' => $exists ? hash_file('sha256', $dst) : null,
            'sha256_payload' => hash_file('sha256', $src),
        ];
        if ($exists) $copy($dst, $backupDir . '/files/' . $rel);
    }
    file_put_contents(
        $backupDir . '/manifest.json',
        json_encode($manifest, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR)
    );
    echo "[OK] Backup criado: {$backupDir}\n";

    // Fase 1: migrations primeiro. Nenhum controller/view novo entra antes do schema ficar pronto.
    $migrationRels = [
        'database/migrations/039_modules_merged_subscription.sql',
        'database/migrations/040_applanner_barber_v1.sql',
    ];
    foreach ($migrationRels as $rel) {
        if (!isset($files[$rel])) throw new RuntimeException('Migration ausente no payload: ' . $rel);
        $copy($files[$rel], $root . '/' . $rel);
    }
    echo "[OK] Migrations 039/040 preparadas\n";

    spl_autoload_register(static function (string $class) use ($root): void {
        $prefix = 'App\\';
        if (!str_starts_with($class, $prefix)) return;
        $file = $root . '/app/' . str_replace('\\', '/', substr($class, strlen($prefix))) . '.php';
        if (is_file($file)) require_once $file;
    });

    $pdo = \App\Core\Database::connection();
    \App\Core\Migrator::run($pdo, $root . '/database/migrations');

    $neededMigrations = ['039_modules_merged_subscription.sql', '040_applanner_barber_v1.sql'];
    $marks = implode(',', array_fill(0, count($neededMigrations), '?'));
    $stmt = $pdo->prepare("SELECT migration FROM migrations WHERE migration IN ({$marks})");
    $stmt->execute($neededMigrations);
    $applied = $stmt->fetchAll(PDO::FETCH_COLUMN);
    foreach ($neededMigrations as $migration) {
        if (!in_array($migration, $applied, true)) {
            throw new RuntimeException('Migration não registrada após execução: ' . $migration);
        }
    }

    // Confirmação mínima do schema operacional Barber.
    foreach ([
        'professional_service_commissions',
        'professional_compensation_models',
        'professional_goals',
        'barber_commands',
        'barber_command_items',
        'barber_command_payments',
        'barber_queue_entries',
        'tenant_recurring_subscriptions',
        'subscription_module_adjustments',
    ] as $table) {
        $q = $pdo->prepare('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?');
        $q->execute([$table]);
        if (!(int)$q->fetchColumn()) throw new RuntimeException('Tabela esperada não foi criada: ' . $table);
    }
    foreach ([
        ['appointments', 'checked_in_at'],
        ['appointments', 'service_started_at'],
        ['appointments', 'service_completed_at'],
        ['customer_memberships', 'billing_mode'],
        ['customer_memberships', 'provider_subscription_id'],
        ['subscriptions', 'addon_contracted_price'],
        ['tenant_module_addons', 'billing_mode'],
    ] as [$table, $column]) {
        $q = $pdo->prepare('SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? AND COLUMN_NAME=?');
        $q->execute([$table, $column]);
        if (!(int)$q->fetchColumn()) throw new RuntimeException("Coluna esperada não foi criada: {$table}.{$column}");
    }
    echo "[OK] Migrations 039/040 aplicadas e schema confirmado\n";

    // Fase 2: libera aplicação somente depois do banco estar compatível.
    foreach ($files as $rel => $src) {
        if (str_starts_with($rel, 'database/migrations/')) continue;
        $copy($src, $root . '/' . $rel);
    }
    echo "[OK] Arquivos da aplicação atualizados\n";

    // Lint dos PHP efetivamente instalados.
    foreach ($files as $rel => $_src) {
        if (!str_ends_with(strtolower($rel), '.php')) continue;
        $output = [];
        $code = $run(escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($root . '/' . $rel), $output);
        if ($code !== 0) {
            throw new RuntimeException('Lint pós-instalação falhou em ' . $rel . ': ' . implode(' ', $output));
        }
    }
    echo "[OK] Lint pós-instalação aprovado\n";

    foreach ([
        'tests/module_subscription_merge_smoke.php',
        'tests/mercadopago_subscription_update_unit.php',
        'tests/barber_v1_smoke.php',
        'tests/barber_recurring_provider_unit.php',
    ] as $test) {
        $output = [];
        $code = $run(escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($root . '/' . $test), $output);
        echo implode("\n", $output) . "\n";
        if ($code !== 0) throw new RuntimeException('Teste pós-instalação falhou: ' . $test);
    }

    $updates = $root . '/storage/updates';
    if (!is_dir($updates) && !mkdir($updates, 0750, true) && !is_dir($updates)) {
        throw new RuntimeException('Não foi possível criar storage/updates.');
    }
    file_put_contents(
        $updates . '/barber-v1.json',
        json_encode([
            'patch' => 'PATCH_APPLANNER_BARBER_V1_COMPLETO',
            'installed_at' => date(DATE_ATOM),
            'backup_dir' => $backupDir,
            'migrations' => $neededMigrations,
        ], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR)
    );

    echo "\nPATCH APPLANNER BARBER V1 COMPLETO INSTALADO.\n";
    echo "Backup: {$backupDir}\n";
} catch (Throwable $e) {
    fwrite(STDERR, "[ERRO] Instalação interrompida: {$e->getMessage()}\n");
    fwrite(STDERR, "Restaurando arquivos a partir de {$backupDir} ...\n");

    foreach (array_reverse($manifest['files']) as $entry) {
        $rel = (string)$entry['path'];
        $dst = $root . '/' . $rel;
        if ($entry['existed']) {
            $src = $backupDir . '/files/' . $rel;
            if (is_file($src)) $copy($src, $dst);
        } elseif (is_file($dst)) {
            @unlink($dst);
        }
    }
    fwrite(STDERR, "Arquivos restaurados. Migrations incrementais já confirmadas não são apagadas automaticamente para evitar perda de dados.\n");
    exit(1);
}
