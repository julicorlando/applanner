<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
$root = dirname(__DIR__);
$backupArg = null;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--backup=')) $backupArg = substr($arg, 9);
}
if (!$backupArg) {
    fwrite(STDERR, "Uso: php tools/rollback-barber-v1.php --backup=/home/.../storage/update-backups/barber-v1-AAAAMMDD-HHMMSS\n");
    exit(1);
}
$backup = realpath($backupArg);
$allowedRoot = realpath($root . '/storage/update-backups');
if (!$backup || !$allowedRoot || !str_starts_with($backup, $allowedRoot . DIRECTORY_SEPARATOR)) {
    fwrite(STDERR, "[ERRO] Backup inválido ou fora de storage/update-backups.\n");
    exit(1);
}
$manifestFile = $backup . '/manifest.json';
if (!is_file($manifestFile)) { fwrite(STDERR, "[ERRO] manifest.json não encontrado.\n"); exit(1); }
$manifest = json_decode((string)file_get_contents($manifestFile), true);
if (!is_array($manifest) || ($manifest['patch'] ?? '') !== 'PATCH_APPLANNER_BARBER_V1_COMPLETO') {
    fwrite(STDERR, "[ERRO] O backup informado não pertence ao Barber V1.\n");
    exit(1);
}
$copy = static function (string $src, string $dst): void {
    $dir = dirname($dst);
    if (!is_dir($dir) && !mkdir($dir,0755,true) && !is_dir($dir)) throw new RuntimeException('Falha ao criar ' . $dir);
    if (!copy($src, $dst)) throw new RuntimeException('Falha ao copiar ' . $dst);
};
try {
    foreach (array_reverse($manifest['files'] ?? []) as $entry) {
        $rel = (string)($entry['path'] ?? '');
        if ($rel === '' || str_contains($rel, '..')) continue;
        $dst = $root . '/' . $rel;
        if (!empty($entry['existed'])) {
            $src = $backup . '/files/' . $rel;
            if (!is_file($src)) throw new RuntimeException('Backup ausente para ' . $rel);
            $copy($src, $dst);
        } elseif (is_file($dst)) {
            @unlink($dst);
        }
    }
    echo "[OK] Arquivos restaurados a partir de {$backup}.\n";
    echo "ATENÇÃO: as migrations 039/040 são aditivas e NÃO foram revertidas automaticamente, para evitar perda de histórico/dados.\n";
} catch (Throwable $e) {
    fwrite(STDERR, "[ERRO] Rollback interrompido: {$e->getMessage()}\n");
    exit(1);
}
