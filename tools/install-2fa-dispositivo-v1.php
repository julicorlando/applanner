<?php
declare(strict_types=1);
$root=dirname(__DIR__);
$patch=$root.'/patches/applanner-2fa-trusted-v1';
$payload=$patch.'/payload';
$dry=in_array('--dry-run',$argv,true);

function out(string $m):void{echo $m.PHP_EOL;}
function copySafe(string $src,string $dst):void{if(!is_file($src))throw new RuntimeException('Arquivo do payload ausente: '.$src);$dir=dirname($dst);if(!is_dir($dir)&&!mkdir($dir,0755,true)&&!is_dir($dir))throw new RuntimeException('Não foi possível criar '.$dir);if(!copy($src,$dst))throw new RuntimeException('Falha ao copiar '.$dst);}
function db(string $root):PDO{$cfg=require $root.'/config/database.php';$dsn=sprintf('mysql:host=%s;port=%d;dbname=%s;charset=%s',$cfg['host'],$cfg['port']??3306,$cfg['database'],$cfg['charset']??'utf8mb4');return new PDO($dsn,$cfg['username'],$cfg['password'],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,PDO::ATTR_EMULATE_PREPARES=>false]);}
function patchIndex(string $index):string{
    $routeAnchor="\$router->post('/security/2fa/confirm', [AuthController::class, 'confirmTwoFactor']);";
    $routes=$routeAnchor."\n\$router->post('/security/2fa/trusted-devices/revoke', [AuthController::class, 'revokeTrustedDevice']);\n\$router->post('/security/2fa/trusted-devices/revoke-all', [AuthController::class, 'revokeAllTrustedDevices']);";
    if(!str_contains($index,"\$router->post('/security/2fa/trusted-devices/revoke'")){
        if(!str_contains($index,$routeAnchor))throw new RuntimeException('Âncora das rotas 2FA não localizada no index.php.');
        $index=str_replace($routeAnchor,$routes,$index);
    }
    $old="'/security/2fa/start','/security/2fa/confirm'";
    $new="'/security/2fa/start','/security/2fa/confirm','/security/2fa/trusted-devices/revoke','/security/2fa/trusted-devices/revoke-all'";
    if(str_contains($index,$old)){
        $index=str_replace($old,$new,$index);
    } elseif(!str_contains($index,$new)){
        throw new RuntimeException('Lista legalExempt compatível não localizada.');
    }
    return $index;
}

$required=['index.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','config/database.php'];
foreach($required as $f)if(!is_file($root.'/'.$f))throw new RuntimeException('Arquivo atual ausente: '.$f);
foreach(['app/Core/TrustedDevice.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','database/migrations/042_two_factor_trusted_devices.sql','tests/two_factor_trusted_device_static.php'] as $f)if(!is_file($payload.'/'.$f))throw new RuntimeException('Payload ausente: '.$f);

$currentIndex=(string)file_get_contents($root.'/index.php');
$patchedIndex=patchIndex($currentIndex);
if($dry){
    out('[OK] Estrutura do patch localizada.');
    out('[OK] index.php pode receber as rotas sem substituir outras rotas.');
    out('[OK] Migration 042 será aplicada antes do código.');
    out('DRY RUN: OK. Nenhuma alteração foi feita.');
    exit(0);
}

$stamp=date('Ymd-His');
$backup=$root.'/storage/update-backups/2fa-dispositivo-v1-'.$stamp;
if(!is_dir($backup)&&!mkdir($backup,0750,true)&&!is_dir($backup))throw new RuntimeException('Não foi possível criar backup: '.$backup);
$files=[
    'index.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','tests/two_factor_trusted_device_static.php'
];
foreach($files as $rel){$src=$root.'/'.$rel;if(is_file($src)){@mkdir($backup.'/'.dirname($rel),0750,true);if(!copy($src,$backup.'/'.$rel))throw new RuntimeException('Falha no backup de '.$rel);}}
out('Backup: '.$backup);

try{
    // 1) Schema primeiro.
    $migrationName='042_two_factor_trusted_devices.sql';
    $migrationSrc=$payload.'/database/migrations/'.$migrationName;
    $migrationDst=$root.'/database/migrations/'.$migrationName;
    copySafe($migrationSrc,$migrationDst);
    $pdo=db($root);
    $pdo->exec("CREATE TABLE IF NOT EXISTS migrations (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, migration VARCHAR(190) NOT NULL UNIQUE, batch INT UNSIGNED NOT NULL, executed_at DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci");
    $q=$pdo->prepare('SELECT COUNT(*) FROM migrations WHERE migration=:m');$q->execute(['m'=>$migrationName]);
    if(!(bool)$q->fetchColumn()){
        $sql=(string)file_get_contents($migrationSrc);
        $pdo->exec($sql);
        $batch=(int)$pdo->query('SELECT COALESCE(MAX(batch),0)+1 FROM migrations')->fetchColumn();
        $ins=$pdo->prepare('INSERT INTO migrations(migration,batch,executed_at) VALUES(:m,:b,NOW())');$ins->execute(['m'=>$migrationName,'b'=>$batch]);
        out('[OK] Migration 042 aplicada.');
    } else out('[OK] Migration 042 já estava registrada.');
    if(!(bool)$pdo->query("SHOW TABLES LIKE 'two_factor_trusted_devices'")->fetchColumn())throw new RuntimeException('Tabela two_factor_trusted_devices não foi encontrada após a migration.');
    $cols=$pdo->query('SHOW COLUMNS FROM two_factor_trusted_devices')->fetchAll(PDO::FETCH_COLUMN);
    foreach(['user_id','selector','validator_hash','session_version','expires_at','revoked_at'] as $col)if(!in_array($col,$cols,true))throw new RuntimeException('Tabela two_factor_trusted_devices incompleta: coluna '.$col.' ausente.');

    // 2) Código depois do schema.
    foreach(['app/Core/TrustedDevice.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','tests/two_factor_trusted_device_static.php'] as $rel)copySafe($payload.'/'.$rel,$root.'/'.$rel);
    if(file_put_contents($root.'/index.php',$patchedIndex,LOCK_EX)===false)throw new RuntimeException('Falha ao atualizar index.php.');

    foreach(['index.php','app/Core/TrustedDevice.php','app/Core/Auth.php','app/Controllers/AuthController.php','app/Views/auth/two-factor-challenge.php','app/Views/auth/security.php','tests/two_factor_trusted_device_static.php'] as $rel){$outp=[];$code=0;exec(PHP_BINARY.' -l '.escapeshellarg($root.'/'.$rel).' 2>&1',$outp,$code);if($code!==0)throw new RuntimeException('PHP lint falhou em '.$rel.': '.implode(' | ',$outp));}
    $test=[];$code=0;exec(PHP_BINARY.' '.escapeshellarg($root.'/tests/two_factor_trusted_device_static.php').' 2>&1',$test,$code);foreach($test as $line)out($line);if($code!==0)throw new RuntimeException('Smoke/static test do dispositivo confiável falhou.');

    out('[OK] Rotas de revogação registradas.');
    out('[OK] 2FA lembrado por 30 dias por usuário/navegador.');
    out('[OK] Troca/reset de senha invalida confiança anterior.');
    out('PATCH 2FA DISPOSITIVO CONFIÁVEL V1 INSTALADO.');
}catch(Throwable $e){
    out('[ERRO] '.$e->getMessage());
    out('Restaurando arquivos a partir de '.$backup.' ...');
    foreach($files as $rel){$src=$backup.'/'.$rel;$dst=$root.'/'.$rel;if(is_file($src)){@mkdir(dirname($dst),0755,true);copy($src,$dst);}elseif($rel==='tests/two_factor_trusted_device_static.php'&&is_file($dst)){@unlink($dst);}}
    out('Arquivos restaurados. A migration 042 é aditiva e pode permanecer para uma nova tentativa.');
    exit(1);
}
