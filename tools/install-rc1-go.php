<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root=dirname(__DIR__);
$payload=$root.'/patches/applanner-rc1-go/payload';
$dry=in_array('--dry-run',$argv,true);

function fail(string $m): never { fwrite(STDERR,"[ERRO] {$m}\n"); exit(1); }
function copyTree(string $src,string $dst,array &$copied): void {
    $it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($src,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::SELF_FIRST);
    foreach($it as $f){
        $rel=substr($f->getPathname(),strlen($src)+1);$to=$dst.'/'.$rel;
        if($f->isDir()){if(!is_dir($to)&&!mkdir($to,0750,true)&&!is_dir($to))fail("Não foi possível criar {$to}");continue;}
        if(!is_dir(dirname($to))&&!mkdir(dirname($to),0750,true)&&!is_dir(dirname($to)))fail("Pasta indisponível: ".dirname($to));
        if(!copy($f->getPathname(),$to))fail("Falha copiando {$rel}");
        $copied[]=$rel;
    }
}
function runPhp(string $file,array $args=[]): array {
    $cmd=escapeshellarg(PHP_BINARY).' '.escapeshellarg($file);
    foreach($args as $a)$cmd.=' '.escapeshellarg($a);
    $o=[];$c=0;@exec($cmd.' 2>&1',$o,$c);return [$c,implode("\n",$o)];
}

if(!is_dir($payload))fail('Payload RC1 não encontrado. Extraia o ZIP na raiz do public_html.');
[$pc,$po]=runPhp($root.'/tools/preflight-rc1-go.php');
echo $po."\n";
if($pc!==0)exit($pc);

if($dry){
    echo "\nDRY RUN RC1: OK.\n";
    echo "- Será criado backup completo pelo BackupService.\n";
    echo "- O backup recém-criado será restaurado em base temporária antes da migration.\n";
    echo "- A migration 043 será aplicada antes do código novo.\n";
    echo "- Crons Arena/Barber/Auto serão registrados preservando os atuais.\n";
    echo "- Somente jobs falhos destinados a example.com/example.com.br poderão ser saneados automaticamente.\n";
    echo "Nenhuma alteração foi feita.\n";
    exit(0);
}

// RC1 V1.1: corrige antes do backup a divergência histórica da APP_KEY.
// Encryption.php usa config/app.php; o BackupService antigo exigia somente getenv(APP_KEY).
$backupServiceSrc=$payload.'/app/Services/BackupService.php';
$backupServiceDst=$root.'/app/Services/BackupService.php';
$prePatchDir=$root.'/storage/update-backups/rc1-v11-prebackup-'.date('Ymd-His');
if(!is_file($backupServiceSrc))fail('BackupService compatível não encontrado no payload V1.1.');
if(!is_dir($prePatchDir)&&!mkdir($prePatchDir,0750,true)&&!is_dir($prePatchDir))fail('Não foi possível criar backup prévio do BackupService.');
if(is_file($backupServiceDst)&&!copy($backupServiceDst,$prePatchDir.'/BackupService.php'))fail('Não foi possível preservar o BackupService anterior.');
if(!copy($backupServiceSrc,$backupServiceDst))fail('Não foi possível aplicar compatibilidade de APP_KEY no BackupService.');
// Lint direto para não executar o serviço.
$lint=[];$lintCode=0;@exec(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($backupServiceDst).' 2>&1',$lint,$lintCode);
if($lintCode!==0){if(is_file($prePatchDir.'/BackupService.php'))@copy($prePatchDir.'/BackupService.php',$backupServiceDst);fail('Lint do BackupService V1.1 falhou: '.implode(' ',$lint));}
echo "[0/10] Compatibilidade APP_KEY do backup aplicada.\n";

// Carrega a versão atual (a migration 043 ainda está apenas dentro do payload).
require $root.'/app/Core/bootstrap.php';
$pdo=\App\Core\Database::connection();

echo "[1/10] Criando backup completo...\n";
try{$dbBackup=(new \App\Services\BackupService())->create('rc1-production-readiness');}
catch(Throwable $e){fail('Backup obrigatório falhou: '.$e->getMessage());}
echo "[OK] Backup DB: ".($dbBackup['name']??$dbBackup['path']??'criado')."\n";

$stamp=date('Ymd-His');
$codeBackup=$root.'/storage/update-backups/rc1-go-'.$stamp.'/files';
$changed=[
 'app/Core/CronLock.php','app/Services/BackupService.php','app/Views/billing/modules.php',
 'cron/worker.php','cron/arena.php','cron/barber.php','cron/auto.php',
 'database/migrations/043_applanner_rc1_production_readiness.sql',
 'tests/rc1_regression_static.php','tools/install-rc1-crons.php',
 'tools/rc1-repair-jobs.php','tools/rc1-acceptance.php','tools/rc1-go-live.php','tools/rc1-verify-backup.php'
];
foreach($changed as $rel){
    $from=$root.'/'.$rel;if(!is_file($from))continue;$to=$codeBackup.'/'.$rel;
    if(!is_dir(dirname($to))&&!mkdir(dirname($to),0750,true)&&!is_dir(dirname($to)))fail('Backup de código indisponível.');
    if(!copy($from,$to))fail('Falha ao salvar backup de '.$rel);
}
file_put_contents(dirname($codeBackup).'/MANIFEST.txt',"RC1 backup {$stamp}\nDB backup id=".($dbBackup['id']??'?')."\n".implode("\n",$changed)."\n",LOCK_EX);

echo "[2/10] Testando restauração isolada do backup...\n";
try{
    $bq=$pdo->prepare("SELECT * FROM backups WHERE id=:id LIMIT 1");$bq->execute(['id'=>(int)($dbBackup['id']??0)]);$backupRow=$bq->fetch();
    if(!$backupRow)throw new RuntimeException('Registro do backup recém-criado não foi localizado.');
    $uq=$pdo->query("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.slug='master' ORDER BY u.id LIMIT 1");
    $verifyUser=(int)$uq->fetchColumn();if($verifyUser<=0)$verifyUser=(int)$pdo->query("SELECT id FROM users ORDER BY id LIMIT 1")->fetchColumn();
    if($verifyUser<=0)throw new RuntimeException('Nenhum usuário disponível para registrar a restauração.');
    $restore=(new \App\Services\BackupService())->testRestore($backupRow,$verifyUser);
    echo "[OK] Restauração isolada: ".(int)($restore['tables']??0)." tabela(s) e base temporária removida.\n";
}catch(Throwable $e){fail('Restauração do backup falhou. O RC1 não será aplicado: '.$e->getMessage());}
echo "[3/10] Instalando migration 043...\n";
$migSrc=$payload.'/database/migrations/043_applanner_rc1_production_readiness.sql';
$migDst=$root.'/database/migrations/043_applanner_rc1_production_readiness.sql';
if(!copy($migSrc,$migDst))fail('Não foi possível copiar migration 043.');
try{\App\Core\Migrator::run($pdo,$root.'/database/migrations');}
catch(Throwable $e){@unlink($migDst);fail('Migration 043 falhou; código RC1 não foi liberado: '.$e->getMessage());}

$db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
$q=$pdo->query("SHOW COLUMNS FROM campaign_recipients LIKE 'status'")->fetch();
if(!$q||!str_contains((string)$q['Type'],"'skipped'"))fail('Schema RC1 não confirmou status skipped.');
if(!$pdo->query("SHOW COLUMNS FROM jobs LIKE 'last_error'")->fetch())fail('Schema RC1 não confirmou jobs.last_error.');
echo "[OK] Schema RC1 validado.\n";

echo "[4/10] Copiando código RC1...\n";
$copied=[];copyTree($payload,$root,$copied);
echo "[OK] ".count($copied)." arquivo(s) de payload processados.\n";

echo "[5/10] PHP lint...\n";
foreach($copied as $rel){
    if(!str_ends_with($rel,'.php'))continue;
    $cmd=escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($root.'/'.$rel).' 2>&1';$lines=[];$code=0;@exec($cmd,$lines,$code);
    if($code!==0)fail("Lint falhou em {$rel}: ".implode(' ',$lines));
}
echo "[OK] PHP lint.\n";

echo "[6/10] Teste de regressão RC1...\n";
[$tc,$to]=runPhp($root.'/tests/rc1_regression_static.php');echo $to."\n";if($tc!==0)fail('Teste RC1 falhou.');

echo "[7/10] Registrando crons especializados...\n";
[$cc,$co]=runPhp($root.'/tools/install-rc1-crons.php',['--apply']);echo $co."\n";
if($cc!==0)echo "[AVISO] Crons não puderam ser gravados automaticamente. O GO checker continuará bloqueando até cadastrá-los.\n";

echo "[8/10] Saneando somente jobs fictícios conhecidos...\n";
[$jc,$jo]=runPhp($root.'/tools/rc1-repair-jobs.php',['--apply-safe']);echo $jo."\n";
if($jc===1)fail('Saneamento seguro de jobs falhou.');
if($jc===2)echo "[AVISO] Existem jobs falhos reais que precisam ser investigados; nenhum deles foi reenviado automaticamente.\n";

echo "[9/10] Executando GO técnico...\n";
[$gc,$go]=runPhp($root.'/tools/rc1-go-live.php');echo $go."\n";

echo "\nPATCH APPLANNER RC1 GO V1.1 INSTALADO.\n";
echo "Backup de código: ".dirname($codeBackup)."\n";
echo "Para validação externa do Mercado Pago: php tools/rc1-go-live.php --external\n";
echo "Para GO comercial final: php tools/rc1-go-live.php --commercial --external\n";
echo "Checklist manual: php tools/rc1-acceptance.php\n";
exit(0);
