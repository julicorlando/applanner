<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$payload = $root . '/patches/applanner-arena-v1/payload';
$errors = [];
$warnings = [];
$ok = [];

$require = static function(bool $condition, string $message) use (&$errors, &$ok): void {
    if ($condition) $ok[] = $message; else $errors[] = $message;
};

$require(version_compare(PHP_VERSION, '8.1.0', '>='), 'PHP >= 8.1');
$require(is_file($root . '/index.php'), 'index.php encontrado');
$require(is_file($root . '/app/Core/bootstrap.php'), 'bootstrap atual encontrado');
$require(is_file($root . '/app/Core/Router.php'), 'Router atual encontrado');
$require(is_file($root . '/database/migrations/035_sports_courts_module.sql'), 'migration 035 de Quadras/Esportes encontrada');
$require(is_file($root . '/storage/installed.lock'), 'instalação ApPlanner reconhecida');
$require(is_dir($payload), 'payload Arena V1 encontrado');
$require(is_file($root . '/tests/arena_v1_smoke.php'), 'smoke test Arena V1 encontrado');

$payloadFiles = [];
if (is_dir($payload)) {
    $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload, FilesystemIterator::SKIP_DOTS));
    foreach ($iterator as $file) {
        if (!$file->isFile()) continue;
        $path = $file->getPathname();
        $payloadFiles[] = $path;
        if (strtolower($file->getExtension()) === 'php') {
            $cmd = escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($path) . ' 2>&1';
            $out = []; $code = 0;
            exec($cmd, $out, $code);
            if ($code !== 0) $errors[] = 'Erro de sintaxe em ' . substr($path, strlen($payload) + 1) . ': ' . implode(' ', $out);
        }
    }
}
$require(count($payloadFiles) >= 20, 'payload contém os arquivos esperados');

$installedMigration = $root . '/database/migrations/037_applanner_arena_v1.sql';
if (is_file($installedMigration) && is_file($payload . '/database/migrations/037_applanner_arena_v1.sql')
    && !hash_equals(hash_file('sha256', $installedMigration), hash_file('sha256', $payload . '/database/migrations/037_applanner_arena_v1.sql'))) {
    $errors[] = 'Já existe uma migration 037_applanner_arena_v1.sql diferente na instalação. Interrompido para evitar colisão de versão.';
}

$migration = $payload . '/database/migrations/037_applanner_arena_v1.sql';
if (is_file($migration)) {
    $sql = file_get_contents($migration) ?: '';
    if (preg_match('/\b(DROP\s+(DATABASE|TABLE)|TRUNCATE\s+TABLE)\b/i', $sql)) $errors[] = 'A migration contém comando destrutivo proibido.';
    else $ok[] = 'migration incremental sem DROP/TRUNCATE';
    foreach (['sports_price_rule_extensions','sports_reservation_finance','sports_memberships','sports_games','sports_waitlist','sports_commands','tenant_payment_connections'] as $table) {
        if (!str_contains($sql, 'CREATE TABLE IF NOT EXISTS ' . $table)) $errors[] = 'Tabela esperada ausente da migration: ' . $table;
    }

    // Foreign keys do InnoDB precisam ter nomes únicos no schema. Detecta colisões
    // com migrations anteriores antes de executar qualquer DDL.
    preg_match_all('/\bCONSTRAINT\s+`?([A-Za-z0-9_]+)`?\s+FOREIGN\s+KEY/i', $sql, $fkMatches);
    $newForeignKeys = array_values(array_unique($fkMatches[1] ?? []));
    $existingForeignKeys = [];
    foreach (glob($root . '/database/migrations/*.sql') ?: [] as $existingFile) {
        if (basename($existingFile) === '037_applanner_arena_v1.sql') continue;
        $existingSql = file_get_contents($existingFile) ?: '';
        preg_match_all('/\bCONSTRAINT\s+`?([A-Za-z0-9_]+)`?\s+FOREIGN\s+KEY/i', $existingSql, $existingMatches);
        foreach ($existingMatches[1] ?? [] as $fkName) $existingForeignKeys[$fkName] = basename($existingFile);
    }
    foreach ($newForeignKeys as $fkName) {
        if (isset($existingForeignKeys[$fkName])) {
            $errors[] = 'Nome de foreign key duplicado: ' . $fkName . ' já existe em ' . $existingForeignKeys[$fkName] . '.';
        }
    }
    if (!$errors) $ok[] = 'nomes de foreign keys sem colisão com migrations anteriores';
} else $errors[] = 'Migration 037 ausente do payload.';

$publicSports = $payload . '/app/Views/public/sports.php';
if (is_file($publicSports)) {
    $text = file_get_contents($publicSports) ?: '';
    if (str_contains($text, 'name="professional_id"')) $errors[] = 'Fluxo público Arena ainda contém professional_id.';
    else $ok[] = 'fluxo público sem professional_id';
}

if (!is_writable($root)) $warnings[] = 'Raiz não está gravável pelo usuário CLI; confirme permissões antes de instalar.';
if (!is_writable($root . '/storage')) $warnings[] = 'storage não está gravável; backup/log de atualização pode falhar.';

foreach ($ok as $message) echo "[OK] {$message}\n";
foreach ($warnings as $message) echo "[AVISO] {$message}\n";
foreach ($errors as $message) fwrite(STDERR, "[ERRO] {$message}\n");

if ($errors) {
    fwrite(STDERR, "\nPRE-FLIGHT: FALHOU. Nada foi alterado.\n");
    exit(1);
}
echo "\nPRE-FLIGHT: OK. Pode executar php tools/install-arena-v1.php\n";
