<?php
declare(strict_types=1);

$storageRoot = __DIR__ . '/../../storage';
foreach (['logs','cache','rate_limits','backups','private','private/support'] as $dir) {
    $path = $storageRoot . '/' . $dir;
    if (!is_dir($path)) @mkdir($path, 0750, true);
}

spl_autoload_register(function (string $class): void {
    $prefix = 'App\\';
    if (!str_starts_with($class, $prefix)) {
        return;
    }
    $relative = substr($class, strlen($prefix));
    $file = __DIR__ . '/../' . str_replace('\\', '/', $relative) . '.php';
    if (is_file($file)) {
        require $file;
    }
});

if (!is_file(__DIR__ . '/../../storage/installed.lock')) {
    if (!str_starts_with($_SERVER['REQUEST_URI'] ?? '/', '/install')) {
        header('Location: /install/');
        exit;
    }
    return;
}

$app = require __DIR__ . '/../../config/app.php';

date_default_timezone_set($app['timezone'] ?? 'America/Recife');

\App\Core\Security::boot($app);
\App\Core\I18n::boot();

set_exception_handler(function (Throwable $e) use ($app): void {
    $errorId = 'ERR-' . date('Ymd') . '-' . strtoupper(substr(bin2hex(random_bytes(4)), 0, 6));
    $method = $_SERVER['REQUEST_METHOD'] ?? 'CLI';
    $uri = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH) ?: '-';
    $userId = $_SESSION['user_id'] ?? '-';
    $tenantId = $_SESSION['tenant_id'] ?? '-';
    $log = sprintf(
        "[%s] [%s] %s in %s:%d | request=%s %s | user=%s | tenant=%s\n%s\n\n",
        date('c'), $errorId, $e->getMessage(), $e->getFile(), $e->getLine(),
        $method, $uri, (string)$userId, (string)$tenantId, $e->getTraceAsString()
    );
    @file_put_contents(__DIR__ . '/../../storage/logs/app.log', $log, FILE_APPEND | LOCK_EX);

    http_response_code(500);
    if (($app['debug'] ?? false) === true) {
        echo '<pre>' . htmlspecialchars($e->__toString(), ENT_QUOTES, 'UTF-8') . '</pre>';
        return;
    }

    try {
        \App\Core\View::render('errors/500', ['title'=>'Erro interno','errorId'=>$errorId]);
    } catch (Throwable) {
        // Última barreira: até o renderer pode falhar durante bootstrap/migration.
        echo '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Erro interno</title><body style="font-family:system-ui;padding:40px;max-width:720px;margin:auto"><h1>Não foi possível concluir esta solicitação.</h1><p>Informe este código ao suporte:</p><p style="font:700 18px monospace">' . htmlspecialchars($errorId, ENT_QUOTES, 'UTF-8') . '</p></body></html>';
    }
});

\App\Core\Migrator::run(\App\Core\Database::connection(), __DIR__ . '/../../database/migrations');
