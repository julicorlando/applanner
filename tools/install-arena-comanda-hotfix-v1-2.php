<?php

declare(strict_types=1);

$root = dirname(__DIR__);
$index = $root . '/index.php';
$view = $root . '/app/Views/arena/commands.php';

function fail(string $message, int $code = 1): never {
    fwrite(STDERR, "[ERRO] {$message}\n");
    exit($code);
}

function lintPhp(string $file): bool {
    $cmd = escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($file) . ' 2>&1';
    exec($cmd, $out, $status);
    if ($status !== 0) {
        fwrite(STDERR, implode("\n", $out) . "\n");
        return false;
    }
    return true;
}

if (!is_file($index)) fail('index.php não encontrado em ' . $index);
if (!is_file($view)) fail('View de comandas não encontrada em ' . $view);

$stamp = date('Ymd-His');
$backupDir = $root . '/storage/update-backups/arena-comanda-v1-2-' . $stamp;
if (!is_dir($backupDir) && !mkdir($backupDir, 0775, true) && !is_dir($backupDir)) {
    fail('Não foi possível criar backup em ' . $backupDir);
}

if (!copy($index, $backupDir . '/index.php')) fail('Falha ao criar backup do index.php');
if (!copy($view, $backupDir . '/commands.php')) fail('Falha ao criar backup da view de comandas');

try {
    $indexContent = file_get_contents($index);
    $viewContent = file_get_contents($view);
    if ($indexContent === false || $viewContent === false) {
        throw new RuntimeException('Não foi possível ler os arquivos atuais.');
    }

    $canonicalRoute = "\$router->post('/sports/commands', [ArenaOperationsController::class, 'openCommand']);";
    $aliasRoute = "\$router->post('/sports/commands/open', [ArenaOperationsController::class, 'openCommand']);";

    if (!str_contains($indexContent, $canonicalRoute)) {
        throw new RuntimeException('Rota canônica POST /sports/commands não foi encontrada no index.php. Hotfix interrompido para não alterar uma estrutura desconhecida.');
    }

    if (!str_contains($indexContent, $aliasRoute)) {
        $indexContent = str_replace($canonicalRoute, $canonicalRoute . PHP_EOL . $aliasRoute, $indexContent, $count);
        if ($count !== 1) {
            throw new RuntimeException('Não foi possível inserir o alias /sports/commands/open com segurança.');
        }
    }

    if (str_contains($viewContent, 'action="/sports/commands/open"')) {
        $viewContent = str_replace('action="/sports/commands/open"', 'action="/sports/commands"', $viewContent);
    }

    if (!str_contains($viewContent, 'action="/sports/commands"')) {
        throw new RuntimeException('Formulário Abrir comanda não pôde ser identificado na view.');
    }

    if (file_put_contents($index, $indexContent, LOCK_EX) === false) {
        throw new RuntimeException('Falha ao salvar index.php.');
    }
    if (file_put_contents($view, $viewContent, LOCK_EX) === false) {
        throw new RuntimeException('Falha ao salvar app/Views/arena/commands.php.');
    }

    if (!lintPhp($index) || !lintPhp($view)) {
        throw new RuntimeException('Lint PHP falhou após a alteração.');
    }

    echo "[OK] Formulário de abertura usa POST /sports/commands.\n";
    echo "[OK] Alias compatível POST /sports/commands/open registrado.\n";
    echo "[OK] PHP lint aprovado.\n";
    echo "Backup: {$backupDir}\n";
    echo "HOTFIX ARENA COMANDA 404 V1.2 APLICADO.\n";
} catch (Throwable $e) {
    @copy($backupDir . '/index.php', $index);
    @copy($backupDir . '/commands.php', $view);
    fail($e->getMessage() . ' Arquivos restaurados do backup.');
}
