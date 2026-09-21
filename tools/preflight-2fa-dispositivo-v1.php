<?php
declare(strict_types=1);
$root=dirname(__DIR__);
$payload=$root.'/patches/applanner-2fa-trusted-v1/payload';
$fail=[];$ok=[];
$assert=function(bool $condition,string $label)use(&$fail,&$ok){if($condition){$ok[]=$label;}else{$fail[]=$label;}echo ($condition?'[OK] ':'[FALHA] ').$label.PHP_EOL;};

$required=[
    'index.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','config/database.php',
];
foreach($required as $file)$assert(is_file($root.'/'.$file),'Arquivo atual: '.$file);
foreach([
    'app/Core/TrustedDevice.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','database/migrations/042_two_factor_trusted_devices.sql','tests/two_factor_trusted_device_static.php'
] as $file)$assert(is_file($payload.'/'.$file),'Payload: '.$file);

$index=(string)@file_get_contents($root.'/index.php');
$assert(str_contains($index,"\$router->post('/security/2fa/confirm', [AuthController::class, 'confirmTwoFactor']);"),'Âncora de rota 2FA localizada');
$assert(str_contains($index,'$legalExempt=['),'Lista de exceções de segurança/legal localizada');

$currentAuth=(string)@file_get_contents($root.'/app/Core/Auth.php');
$currentController=(string)@file_get_contents($root.'/app/Controllers/AuthController.php');
$assert(str_contains($currentAuth,'public static function attempt(string $email, string $password): bool'),'Auth::attempt compatível');
$assert(str_contains($currentController,'public function verifyTwoFactorChallenge(): void'),'Challenge 2FA atual localizado');

$migration=(string)@file_get_contents($payload.'/database/migrations/042_two_factor_trusted_devices.sql');
$assert(!preg_match('/\b(DROP\s+TABLE|TRUNCATE|DROP\s+DATABASE)\b/i',$migration),'Migration 042 sem comandos destrutivos');

try{
    $cfg=require $root.'/config/database.php';
    $dsn=sprintf('mysql:host=%s;port=%d;dbname=%s;charset=%s',$cfg['host'],$cfg['port']??3306,$cfg['database'],$cfg['charset']??'utf8mb4');
    $pdo=new PDO($dsn,$cfg['username'],$cfg['password'],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC]);
    $cols=$pdo->query("SHOW COLUMNS FROM users")->fetchAll(PDO::FETCH_COLUMN);
    $assert(in_array('two_factor_secret',$cols,true),'users.two_factor_secret existente');
    $assert(in_array('session_version',$cols,true),'users.session_version existente');
    $assert((bool)$pdo->query("SHOW TABLES LIKE 'two_factor_recovery_codes'")->fetchColumn(),'Tabela two_factor_recovery_codes existente');
    $fk=$pdo->query("SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_TYPE='FOREIGN KEY' AND CONSTRAINT_NAME='fk_2ftd_user' AND TABLE_NAME<>'two_factor_trusted_devices'")->fetchColumn();
    $assert((int)$fk===0,'Nome de Foreign Key fk_2ftd_user sem colisão no schema');
}catch(Throwable $e){$assert(false,'Conexão/estrutura do banco: '.$e->getMessage());}

foreach([
    $payload.'/app/Core/TrustedDevice.php',$payload.'/app/Core/Auth.php',$payload.'/app/Controllers/AuthController.php',$payload.'/app/Views/auth/two-factor-challenge.php',$payload.'/app/Views/auth/security.php',$payload.'/tests/two_factor_trusted_device_static.php'
] as $file){
    $out=[];$code=0;exec(PHP_BINARY.' -l '.escapeshellarg($file).' 2>&1',$out,$code);$assert($code===0,'PHP lint: '.basename($file));
}

if($fail){echo PHP_EOL.'PRE-FLIGHT: FALHOU ('.count($fail).' item(ns)). Nenhuma alteração do patch foi feita.'.PHP_EOL;exit(1);} 
echo PHP_EOL.'PRE-FLIGHT 2FA DISPOSITIVO V1: OK. Nenhuma alteração do patch foi feita.'.PHP_EOL;
