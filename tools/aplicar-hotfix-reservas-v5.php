<?php
declare(strict_types=1);
$root = dirname(__DIR__);
$index = $root . '/index.php';
if (!is_file($index)) { fwrite(STDERR, "ERRO: index.php não encontrado.\n"); exit(1); }
$c = file_get_contents($index);
if ($c === false) { fwrite(STDERR, "ERRO: não foi possível ler index.php.\n"); exit(1); }
$original = $c;

if (strpos($c, 'SportsReservationsController') === false) {
    if (preg_match('/use App\\\\Controllers\\\\\{([^}]+)\};/', $c, $m)) {
        $list = $m[1];
        if (strpos($list, 'SportsReservationsController') === false) {
            $newList = preg_replace('/(?<![A-Za-z0-9_])SportsController(?=,|$)/', 'SportsController,SportsReservationsController', $list, 1, $count);
            if (!$count) $newList = rtrim($list, ',') . ',SportsReservationsController';
            $c = str_replace($m[0], 'use App\\Controllers\\{' . $newList . '};', $c);
        }
    } else {
        $needle = "use App\\Controllers\\SportsController;";
        if (strpos($c, $needle) !== false) {
            $c = str_replace($needle, $needle . "\nuse App\\Controllers\\SportsReservationsController;", $c);
        } else {
            fwrite(STDERR, "ERRO: formato de imports do index.php não reconhecido. Nenhuma alteração foi feita.\n"); exit(2);
        }
    }
}

$replacements = [
    "\$router->get('/sports/reservations', [SportsController::class, 'reservations']);" => "\$router->get('/sports/reservations', [SportsReservationsController::class, 'index']);",
    "\$router->post('/sports/reservations', [SportsController::class, 'storeReservation']);" => "\$router->post('/sports/reservations', [SportsReservationsController::class, 'store']);",
    "\$router->post('/sports/reservations/{id}/update', [SportsController::class, 'updateReservation']);" => "\$router->post('/sports/reservations/{id}/update', [SportsReservationsController::class, 'update']);",
];
foreach ($replacements as $old => $new) {
    if (strpos($c, $new) !== false) continue;
    if (strpos($c, $old) === false) { fwrite(STDERR, "ERRO: rota esperada não encontrada: $old\n"); exit(3); }
    $c = str_replace($old, $new, $c);
}

if ($c === $original) { echo "OK: hotfix V5 já estava aplicado.\n"; exit(0); }
$backup = $index . '.bak-reservations-v5-' . date('Ymd-His');
if (!copy($index, $backup)) { fwrite(STDERR, "ERRO: falha ao criar backup.\n"); exit(4); }
if (file_put_contents($index, $c) === false) { fwrite(STDERR, "ERRO: falha ao gravar index.php.\n"); exit(5); }
echo "OK: hotfix de reservas esportivas V5 aplicado.\nBackup: $backup\n";
