<?php
declare(strict_types=1);

$root = dirname(__DIR__);
foreach (['storage','storage/logs','storage/cache','storage/rate_limits','storage/backups','storage/private','storage/private/support'] as $dir) {
    $path = $root . '/' . $dir;
    if (!is_dir($path) && !@mkdir($path, 0750, true) && !is_dir($path)) { http_response_code(500); exit('Não foi possível preparar o diretório ' . htmlspecialchars($dir, ENT_QUOTES, 'UTF-8') . '.'); }
}
$lock = $root . '/storage/installed.lock';

if (is_file($lock)) {
    http_response_code(403);
    exit('O sistema já está instalado. Remova o arquivo storage/installed.lock apenas em manutenção controlada.');
}

session_start();
$errors = [];
$success = false;

spl_autoload_register(function (string $class) use ($root): void {
    if (!str_starts_with($class, 'App\\')) return;
    $file = $root . '/app/' . str_replace('\\', '/', substr($class, 4)) . '.php';
    if (is_file($file)) require $file;
});

function h(string $v): string { return htmlspecialchars($v, ENT_QUOTES, 'UTF-8'); }

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!isset($_SESSION['_install_csrf']) || !hash_equals($_SESSION['_install_csrf'], $_POST['_csrf'] ?? '')) {
        $errors[] = 'Requisição inválida.';
    } else {
        $appName = trim((string)($_POST['app_name'] ?? ''));
        $appUrl = rtrim(trim((string)($_POST['app_url'] ?? '')), '/');
        $dbHost = trim((string)($_POST['db_host'] ?? 'localhost'));
        $dbPort = (int)($_POST['db_port'] ?? 3306);
        $dbName = trim((string)($_POST['db_name'] ?? ''));
        $dbUser = trim((string)($_POST['db_user'] ?? ''));
        $dbPass = (string)($_POST['db_pass'] ?? '');
        $masterName = trim((string)($_POST['master_name'] ?? ''));
        $masterEmail = mb_strtolower(trim((string)($_POST['master_email'] ?? '')));
        $masterPass = (string)($_POST['master_password'] ?? '');
        $masterConfirm = (string)($_POST['master_password_confirmation'] ?? '');
        $timezone = (string)($_POST['timezone'] ?? 'America/Sao_Paulo');
        $systemEmail = mb_strtolower(trim((string)($_POST['system_email'] ?? '')));

        if ($appName === '' || !filter_var($appUrl, FILTER_VALIDATE_URL)) $errors[] = 'Nome e URL da aplicação são obrigatórios.';
        if ($dbName === '' || $dbUser === '') $errors[] = 'Informe o banco e usuário MySQL.';
        if ($masterName === '' || !filter_var($masterEmail, FILTER_VALIDATE_EMAIL)) $errors[] = 'Dados do usuário Master inválidos.';
        if (strlen($masterPass) < 12 || !preg_match('/[A-Z]/', $masterPass) || !preg_match('/[a-z]/', $masterPass) || !preg_match('/\d/', $masterPass) || !preg_match('/[^A-Za-z0-9]/', $masterPass)) $errors[] = 'A senha Master deve ter 12 caracteres, maiúscula, minúscula, número e símbolo.';
        if (!hash_equals($masterPass, $masterConfirm)) $errors[] = 'A confirmação da senha não confere.';
        if (!in_array($timezone, timezone_identifiers_list(), true)) $errors[] = 'Timezone inválido.';
        if (!filter_var($systemEmail, FILTER_VALIDATE_EMAIL)) $errors[] = 'E-mail do sistema inválido.';
        if (!extension_loaded('pdo_mysql')) $errors[] = 'A extensão pdo_mysql não está habilitada.';
        if (!extension_loaded('mbstring')) $errors[] = 'A extensão mbstring não está habilitada.';
        if (!extension_loaded('openssl')) $errors[] = 'A extensão openssl não está habilitada.';
        if (!extension_loaded('curl')) $errors[] = 'A extensão curl não está habilitada (necessária para Mercado Pago).';
        if (!extension_loaded('fileinfo')) $errors[] = 'A extensão fileinfo não está habilitada (necessária para uploads seguros).';
        if (version_compare(PHP_VERSION, '8.2.0', '<')) $errors[] = 'É necessário PHP 8.2 ou superior.';

        if (!$errors) {
            try {
                $dsn = "mysql:host={$dbHost};port={$dbPort};dbname={$dbName};charset=utf8mb4";
                $pdo = new PDO($dsn, $dbUser, $dbPass, [
                    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
                    PDO::ATTR_EMULATE_PREPARES => false,
                ]);

                $sql = file_get_contents($root . '/database/schema.sql');
                $statements = array_filter(array_map('trim', preg_split('/;\s*(?:\r?\n|$)/', $sql)));
                foreach ($statements as $stmt) {
                    if ($stmt !== '') $pdo->exec($stmt);
                }

                $pdo->exec("INSERT IGNORE INTO roles (id,slug,name) VALUES
                    (1,'master','Administrador da plataforma'),
                    (2,'owner','Proprietário'),
                    (3,'manager','Gerente'),
                    (4,'professional','Profissional'),
                    (5,'reception','Recepção')");

                $pdo->exec("INSERT IGNORE INTO plans (name,slug,monthly_price,active,features_json,created_at,updated_at) VALUES
                    ('Inicial','start',49.90,1,JSON_OBJECT('professionals',1,'behavior',false),NOW(),NOW()),
                    ('Profissional','pro',99.90,1,JSON_OBJECT('professionals',5,'behavior',true),NOW(),NOW()),
                    ('Empresarial','business',199.90,1,JSON_OBJECT('professionals',20,'behavior',true,'multiunit',true),NOW(),NOW()),
                    ('Saúde','health',299.90,1,JSON_OBJECT('professionals',20,'behavior',true,'medical',true),NOW(),NOW())");

                \App\Core\Migrator::run($pdo, $root . '/database/migrations');

                $check = $pdo->prepare("SELECT id FROM users WHERE email=:email");
                $check->execute(['email'=>$masterEmail]);
                if ($check->fetchColumn()) throw new RuntimeException('Já existe usuário com este e-mail.');

                $stmt = $pdo->prepare(
                    "INSERT INTO users (tenant_id,name,email,password_hash,status,created_at,updated_at)
                     VALUES (NULL,:name,:email,:hash,'active',NOW(),NOW())"
                );
                $stmt->execute([
                    'name'=>$masterName,
                    'email'=>$masterEmail,
                    'hash'=>password_hash($masterPass, PASSWORD_DEFAULT)
                ]);
                $userId = (int)$pdo->lastInsertId();

                $stmt = $pdo->prepare("INSERT INTO user_roles (user_id,role_id) VALUES (:uid,1)");
                $stmt->execute(['uid'=>$userId]);

                $appCfg = "<?php\nreturn " . var_export([
                    'name'=>$appName,
                    'version'=>'4.0.0 RC',
                    'url'=>$appUrl,
                    'env'=>'production',
                    'debug'=>false,
                    'timezone'=>$timezone,
                    'session_name'=>'agenda_saas_session',
                    'app_key'=>base64_encode(random_bytes(32)),
                    'system_email'=>$systemEmail,
                ], true) . ";\n";

                $dbCfg = "<?php\nreturn " . var_export([
                    'host'=>$dbHost,'port'=>$dbPort,'database'=>$dbName,'username'=>$dbUser,'password'=>$dbPass,'charset'=>'utf8mb4'
                ], true) . ";\n";

                if (file_put_contents($root . '/config/app.php', $appCfg, LOCK_EX) === false) throw new RuntimeException('Falha ao gravar config/app.php');
                if (file_put_contents($root . '/config/database.php', $dbCfg, LOCK_EX) === false) throw new RuntimeException('Falha ao gravar config/database.php');

                file_put_contents($lock, "installed_at=" . date('c') . "\n", LOCK_EX);
                @chmod($root . '/config/app.php', 0640);
                @chmod($root . '/config/database.php', 0640);
                @chmod($lock, 0640);
                $success = true;
            } catch (Throwable $e) {
                @file_put_contents($root . '/storage/logs/install.log', '[' . date('c') . '] ' . $e . "\n", FILE_APPEND | LOCK_EX);
                $errors[] = 'Falha na instalação. Verifique os dados e consulte storage/logs/install.log.';
            }
        }
    }
}

if (empty($_SESSION['_install_csrf'])) $_SESSION['_install_csrf'] = bin2hex(random_bytes(32));
?>
<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Instalador • Agenda SaaS</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head><body class="bg-light">
<div class="container py-5"><div class="row justify-content-center"><div class="col-lg-8">
<div class="card border-0 shadow-sm"><div class="card-body p-4 p-lg-5">
<h1 class="h3">Instalador do Agenda SaaS</h1>
<p class="text-secondary">Preencha os dados abaixo. O instalador cria as tabelas, configura a conexão e bloqueia novas instalações.</p>

<?php if ($success): ?>
<div class="alert alert-success"><strong>Instalação concluída.</strong> O usuário Master foi criado.</div>
<a class="btn btn-primary" href="/login">Ir para o login</a>
<?php else: ?>

<?php foreach($errors as $e): ?><div class="alert alert-danger"><?= h($e) ?></div><?php endforeach; ?>

<div class="alert alert-info small">
Requisitos: PHP 8.2+, PDO MySQL, mod_rewrite/AllowOverride ativo, HTTPS e banco MySQL/MariaDB.
</div>

<form method="post" autocomplete="off">
<input type="hidden" name="_csrf" value="<?= h($_SESSION['_install_csrf']) ?>">
<h2 class="h5 mt-4">Aplicação</h2>
<div class="row g-3">
<div class="col-md-6"><label class="form-label">Nome do sistema</label><input class="form-control" name="app_name" value="ApPlanner" required></div>
<div class="col-md-6"><label class="form-label">URL</label><input class="form-control" name="app_url" placeholder="https://agenda.seudominio.com.br" required></div>
<div class="col-md-6"><label class="form-label">E-mail do sistema</label><input class="form-control" type="email" name="system_email" required></div>
<div class="col-md-6"><label class="form-label">Timezone</label><select class="form-select" name="timezone"><option value="America/Sao_Paulo">America/Sao_Paulo</option><option value="America/Recife">America/Recife</option><option value="America/Manaus">America/Manaus</option></select></div>
</div>

<h2 class="h5 mt-4">Banco MySQL</h2>
<div class="row g-3">
<div class="col-md-4"><label class="form-label">Host</label><input class="form-control" name="db_host" value="localhost" required></div>
<div class="col-md-2"><label class="form-label">Porta</label><input class="form-control" name="db_port" value="3306" required></div>
<div class="col-md-6"><label class="form-label">Banco</label><input class="form-control" name="db_name" required></div>
<div class="col-md-6"><label class="form-label">Usuário</label><input class="form-control" name="db_user" required></div>
<div class="col-md-6"><label class="form-label">Senha</label><input class="form-control" type="password" name="db_pass"></div>
</div>

<h2 class="h5 mt-4">Usuário Master</h2>
<div class="row g-3">
<div class="col-md-4"><label class="form-label">Nome</label><input class="form-control" name="master_name" required></div>
<div class="col-md-4"><label class="form-label">E-mail</label><input class="form-control" type="email" name="master_email" required></div>
<div class="col-md-4"><label class="form-label">Senha forte</label><input class="form-control" type="password" name="master_password" minlength="12" required></div>
<div class="col-md-4"><label class="form-label">Confirmar senha</label><input class="form-control" type="password" name="master_password_confirmation" minlength="12" required></div>
</div>

<button class="btn btn-primary mt-4">Instalar sistema</button>
</form>
<?php endif; ?>
</div></div></div></div></div></body></html>
