<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$payload = $root . '/patches/applanner-arena-v1/payload';
$backupRoot = $root . '/storage/update-backups';
$stamp = date('Ymd-His');
$backupDir = $backupRoot . '/arena-v1-' . $stamp;
$manifest = ['patch'=>'APPLANNER_ARENA_V1','created_at'=>date(DATE_ATOM),'backup_dir'=>$backupDir,'files'=>[]];

$fail = static function(string $message): never {
    fwrite(STDERR, "[ERRO] {$message}\n");
    exit(1);
};
$copy = static function(string $source, string $destination): void {
    $dir = dirname($destination);
    if (!is_dir($dir) && !mkdir($dir, 0755, true) && !is_dir($dir)) throw new RuntimeException('Falha ao criar ' . $dir);
    if (!copy($source, $destination)) throw new RuntimeException('Falha ao copiar ' . $destination);
};

if (!is_file($root . '/storage/installed.lock')) $fail('Este diretório não parece ser a instalação ativa do ApPlanner.');
if (!is_file($root . '/database/migrations/035_sports_courts_module.sql')) $fail('Migration 035 não encontrada. Atualize a base de Quadras/Esportes primeiro.');
if (!is_dir($payload)) $fail('Payload do patch não encontrado.');
if (!is_file($root . '/tests/arena_v1_smoke.php')) $fail('Teste smoke Arena V1 não encontrado. Extraia o pacote completo antes de instalar.');
$payloadMigration = $payload . '/database/migrations/037_applanner_arena_v1.sql';
$installedMigration = $root . '/database/migrations/037_applanner_arena_v1.sql';
if (!is_file($payloadMigration)) $fail('Migration 037 ausente do payload.');
if (is_file($installedMigration) && !hash_equals(hash_file('sha256', $installedMigration), hash_file('sha256', $payloadMigration))) {
    $fail('Já existe uma migration 037_applanner_arena_v1.sql diferente. Interrompido para evitar colisão de versão.');
}
$sql = file_get_contents($payloadMigration) ?: '';
if (preg_match('/\b(DROP\s+(DATABASE|TABLE)|TRUNCATE\s+TABLE)\b/i', $sql)) $fail('A migration contém comando destrutivo proibido.');
$files = [];
$iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload, FilesystemIterator::SKIP_DOTS));
foreach ($iterator as $file) {
    if (!$file->isFile()) continue;
    $source = $file->getPathname();
    $relative = str_replace('\\','/',substr($source, strlen($payload) + 1));
    $files[$relative] = $source;
}
ksort($files);

// Lint integral do payload antes de tocar na instalação.
foreach ($files as $relative => $source) {
    if (str_ends_with(strtolower($relative), '.php')) {
        $cmd = escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($source) . ' 2>&1';
        $out = []; $code = 0;
        exec($cmd, $out, $code);
        if ($code !== 0) $fail('Sintaxe inválida no payload: ' . $relative . ' — ' . implode(' ', $out));
    }
}

if (in_array('--dry-run', $argv, true)) {
    echo "[OK] Instalação ApPlanner reconhecida\n";
    echo "[OK] Payload validado: " . count($files) . " arquivo(s)\n";
    echo "[OK] Nenhum arquivo ou dado foi alterado\n\n";
    echo "DRY RUN: OK. Execute sem --dry-run para instalar.\n";
    exit(0);
}

if (!is_dir($backupRoot) && !mkdir($backupRoot, 0750, true) && !is_dir($backupRoot)) $fail('Não foi possível criar storage/update-backups.');
if (!mkdir($backupDir, 0750, true) && !is_dir($backupDir)) $fail('Não foi possível criar o backup da atualização.');

try {
    // 1) Backup/listagem dos arquivos que serão modificados.
    foreach ($files as $relative => $source) {
        $destination = $root . '/' . $relative;
        $entry = [
            'path'=>$relative,
            'existed'=>is_file($destination),
            'sha256_before'=>is_file($destination) ? hash_file('sha256', $destination) : null,
            'sha256_payload'=>hash_file('sha256', $source),
        ];
        if ($entry['existed']) $copy($destination, $backupDir . '/files/' . $relative);
        $manifest['files'][] = $entry;
    }
    file_put_contents($backupDir . '/manifest.json', json_encode($manifest, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));

    // 2) Atualização de arquivos.
    foreach ($files as $relative => $source) $copy($source, $root . '/' . $relative);

    // 3) Lint dos arquivos efetivamente instalados.
    foreach ($files as $relative => $source) {
        if (!str_ends_with(strtolower($relative), '.php')) continue;
        $installed = $root . '/' . $relative;
        $cmd = escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($installed) . ' 2>&1';
        $out = []; $code = 0;
        exec($cmd, $out, $code);
        if ($code !== 0) throw new RuntimeException('Lint pós-cópia falhou em ' . $relative . ': ' . implode(' ', $out));
    }

    // 4) Bootstrap executa migrations incrementais pela infraestrutura nativa do ApPlanner.
    $_SERVER['REQUEST_URI'] = '/__arena_patch_cli__';
    $_SERVER['REQUEST_METHOD'] = 'CLI';
    require $root . '/app/Core/bootstrap.php';

    // 5) Smoke test em processo separado para validar migration, tabelas e permissões.
    $smokeCmd = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg($root . '/tests/arena_v1_smoke.php') . ' 2>&1';
    $smokeOut = []; $smokeCode = 0;
    exec($smokeCmd, $smokeOut, $smokeCode);
    if ($smokeCode !== 0) throw new RuntimeException('Smoke test Arena V1 falhou: ' . implode(' | ', $smokeOut));

    // 6) Registro de versão sem alterar configuração existente.
    $updatesDir = $root . '/storage/updates';
    if (!is_dir($updatesDir)) @mkdir($updatesDir, 0750, true);
    @file_put_contents($updatesDir . '/arena-v1.json', json_encode([
        'patch'=>'APPLANNER_ARENA_V1','installed_at'=>date(DATE_ATOM),'backup_dir'=>$backupDir
    ], JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));

    echo "[OK] Arquivos atualizados\n";
    echo "[OK] Migration 037 processada pela infraestrutura do ApPlanner\n";
    echo "[OK] Smoke test Arena V1 aprovado\n";
    echo "[OK] Backup: {$backupDir}\n";
    echo "\nPATCH APPLANNER ARENA V1 INSTALADO.\n";
    echo "Validação adicional disponível: php tests/arena_v1_smoke.php\n";
} catch (Throwable $e) {
    fwrite(STDERR, "[ERRO] Instalação interrompida: {$e->getMessage()}\n");
    fwrite(STDERR, "Restaurando arquivos a partir de {$backupDir} ...\n");
    foreach (array_reverse($manifest['files']) as $entry) {
        $relative = $entry['path'];
        $destination = $root . '/' . $relative;
        if ($entry['existed']) {
            $source = $backupDir . '/files/' . $relative;
            if (is_file($source)) $copy($source, $destination);
        } elseif (is_file($destination)) {
            @unlink($destination);
        }
    }
    fwrite(STDERR, "Arquivos restaurados. Tabelas incrementais eventualmente criadas pela migration são preservadas para não apagar dados; a migration é idempotente e pode ser reaplicada após corrigir a causa.\n");
    exit(1);
}
