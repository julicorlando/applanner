<?php
/**
 * Aplica de forma idempotente a rota pública canônica do módulo Quadras e Esportes.
 * Execute na raiz do ApPlanner:
 *   php tools/aplicar-rota-publica-quadras-v4.php
 */

$root = dirname(__DIR__);
$index = $root . '/index.php';

if (!is_file($index)) {
    fwrite(STDERR, "ERRO: index.php não encontrado em {$root}.\n");
    exit(1);
}

$contents = file_get_contents($index);
if ($contents === false) {
    fwrite(STDERR, "ERRO: não foi possível ler index.php.\n");
    exit(1);
}

$original = $contents;

// 1) Importa o novo controller no use agrupado existente.
if (strpos($contents, 'PublicEntryController') === false) {
    $needle = 'PublicBookingController,';
    if (strpos($contents, $needle) === false) {
        fwrite(STDERR, "ERRO: não encontrei PublicBookingController no bloco use de index.php. Nenhuma alteração foi aplicada.\n");
        exit(2);
    }
    $contents = str_replace($needle, 'PublicBookingController,PublicEntryController,', $contents, $countUse);
    if ($countUse < 1) {
        fwrite(STDERR, "ERRO: falha ao adicionar PublicEntryController ao index.php.\n");
        exit(2);
    }
}

// 2) Apenas o GET principal /a/{slug} passa pelo despachante de segmento.
$oldRoute = "\$router->get('/a/{slug}', [PublicBookingController::class, 'show']);";
$newRoute = "\$router->get('/a/{slug}', [PublicEntryController::class, 'show']);";

if (strpos($contents, $newRoute) === false) {
    if (strpos($contents, $oldRoute) === false) {
        fwrite(STDERR, "ERRO: rota /a/{slug} esperada não encontrada. Nenhuma alteração foi aplicada.\n");
        exit(3);
    }
    $contents = str_replace($oldRoute, $newRoute, $contents, $countRoute);
    if ($countRoute !== 1) {
        fwrite(STDERR, "ERRO: quantidade inesperada de rotas alteradas ({$countRoute}). Nenhuma alteração foi aplicada.\n");
        exit(3);
    }
}

if ($contents === $original) {
    echo "OK: rota pública de Quadras e Esportes já estava aplicada.\n";
    exit(0);
}

$backup = $index . '.bak-quadras-v4-' . date('Ymd-His');
if (!copy($index, $backup)) {
    fwrite(STDERR, "ERRO: não foi possível criar backup de index.php.\n");
    exit(4);
}

if (file_put_contents($index, $contents, LOCK_EX) === false) {
    @copy($backup, $index);
    fwrite(STDERR, "ERRO: não foi possível gravar index.php. Backup restaurado.\n");
    exit(5);
}

echo "OK: rota /a/{slug} agora detecta Quadras e Esportes.\n";
echo "Backup: {$backup}\n";
echo "Exemplo esperado: /a/ARENADEMO -> /arena/arena-applanner-demo\n";
