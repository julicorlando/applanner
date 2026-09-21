<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$apply = in_array('--apply', $argv, true);
$remove = in_array('--remove', $argv, true);
$root = realpath(dirname(__DIR__)) ?: dirname(__DIR__);
$php = realpath(PHP_BINARY) ?: PHP_BINARY;
$begin = '# APPLANNER_RC1_BEGIN';
$end = '# APPLANNER_RC1_END';
$block = [
    $begin,
    "* * * * * " . escapeshellarg($php) . " " . escapeshellarg($root . '/cron/arena.php') . " >> " . escapeshellarg($root . '/storage/logs/arena-cron.log') . " 2>&1",
    "*/5 * * * * " . escapeshellarg($php) . " " . escapeshellarg($root . '/cron/barber.php') . " >> " . escapeshellarg($root . '/storage/logs/barber-cron.log') . " 2>&1",
    "*/5 * * * * " . escapeshellarg($php) . " " . escapeshellarg($root . '/cron/auto.php') . " >> " . escapeshellarg($root . '/storage/logs/auto-cron.log') . " 2>&1",
    $end,
];

function runCommand(string $cmd, ?int &$code = null): string {
    $out = [];
    @exec($cmd . ' 2>&1', $out, $code);
    return trim(implode("\n", $out));
}

$whichCode = 0;
$crontabBin = runCommand('command -v crontab', $whichCode);
if ($whichCode !== 0 || $crontabBin === '') {
    echo "[AVISO] Comando crontab não está disponível para este usuário.\n";
    echo "Cadastre manualmente no cPanel:\n\n" . implode("\n", array_slice($block,1,-1)) . "\n";
    exit($apply ? 2 : 0);
}

$listCode = 0;
$current = runCommand(escapeshellarg($crontabBin) . ' -l', $listCode);
if ($listCode !== 0) $current = '';

$current = preg_replace(
    '/^' . preg_quote($begin, '/') . '$.*?^' . preg_quote($end, '/') . '$\R?/ms',
    '',
    $current
) ?? $current;
if ($remove) {
    $newCron = rtrim($current) . ($current !== '' ? "\n" : '');
    if (!$apply) { echo "DRY RUN: o bloco APPLANNER_RC1 será removido.\n"; exit(0); }
    $tmp = tempnam(sys_get_temp_dir(), 'applanner-cron-');
    if (!$tmp) { fwrite(STDERR, "Não foi possível criar arquivo temporário.\n"); exit(1); }
    file_put_contents($tmp, $newCron, LOCK_EX);
    $installCode = 0; $out = runCommand(escapeshellarg($crontabBin) . ' ' . escapeshellarg($tmp), $installCode); @unlink($tmp);
    if ($installCode !== 0) { fwrite(STDERR, "[ERRO] crontab recusou a remoção: {$out}\n"); exit(1); }
    echo "[OK] Bloco APPLANNER_RC1 removido; demais crons preservados.\n"; exit(0);
}

$current = rtrim($current) . ($current !== '' ? "\n" : '') . implode("\n", $block) . "\n";

echo "BLOCO RC1 PROPOSTO:\n";
echo implode("\n", $block) . "\n\n";
if (!$apply) {
    echo "DRY RUN. Use --apply para registrar preservando o restante do crontab.\n";
    exit(0);
}

$tmp = tempnam(sys_get_temp_dir(), 'applanner-cron-');
if (!$tmp) { fwrite(STDERR, "Não foi possível criar arquivo temporário.\n"); exit(1); }
file_put_contents($tmp, $current, LOCK_EX);
$installCode = 0;
$out = runCommand(escapeshellarg($crontabBin) . ' ' . escapeshellarg($tmp), $installCode);
@unlink($tmp);
if ($installCode !== 0) {
    fwrite(STDERR, "[ERRO] crontab recusou a instalação: {$out}\n");
    exit(1);
}
echo "[OK] Crons Arena, Barber e Auto registrados sem remover os crons existentes.\n";
