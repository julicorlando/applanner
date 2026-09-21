<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
require $root.'/app/Core/bootstrap.php';

use App\Core\Database;
use App\Services\BackupService;

$mode=$argv[1]??'';
$state=getenv('APPLANNER_PREHOMOLOG_STATE') ?: (sys_get_temp_dir().'/applanner-prehomolog-state.json');
$pdo=Database::connection();

function hfail(string $m):never{fwrite(STDERR,"[ERRO] {$m}\n");exit(1);}
function masterId(PDO $pdo):int{
    $id=(int)$pdo->query("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.slug='master' ORDER BY u.id LIMIT 1")->fetchColumn();
    if(!$id)hfail('Usuário Master não localizado.');
    return $id;
}
function stateWrite(string $path,array $data):void{
    if(file_put_contents($path,json_encode($data,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES),LOCK_EX)===false)hfail('Não foi possível gravar state temporário.');
    @chmod($path,0600);
}
function stateRead(string $path):array{
    if(!is_file($path))return [];
    $x=json_decode((string)file_get_contents($path),true);
    return is_array($x)?$x:[];
}

if($mode==='prepare'){
    echo "[1/10] Criando backup temporário de segurança...\n";
    try{
        $svc=new BackupService();
        $b=$svc->create('pre-homologacao-final-clean');
        $id=(int)($b['id']??0);
        if(!$id)throw new RuntimeException('Backup sem ID.');
        $q=$pdo->prepare("SELECT * FROM backups WHERE id=:id");$q->execute(['id'=>$id]);$row=$q->fetch(PDO::FETCH_ASSOC);
        if(!$row)throw new RuntimeException('Registro do backup não encontrado.');
        $restore=$svc->testRestore($row,masterId($pdo));
        $src=(string)($row['path']??'');
        if($src===''||!is_file($src))throw new RuntimeException('Arquivo criptografado do backup não encontrado.');
        $tmp=sys_get_temp_dir().'/applanner-prehomolog-'.date('Ymd-His').'-'.getmypid().'.zip.enc';
        if(!copy($src,$tmp))throw new RuntimeException('Não foi possível copiar backup para /tmp.');
        stateWrite($state,['backup_temp'=>$tmp,'backup_source_id'=>$id,'created_at'=>date(DATE_ATOM)]);
        echo "[OK] Backup temporário criado e restauração testada: ".(int)($restore['tables']??0)." tabela(s).\n";
        echo "[OK] Cópia de segurança temporária: {$tmp}\n";
        exit(0);
    }catch(Throwable $e){hfail('Backup temporário falhou: '.$e->getMessage());}
}

if($mode==='baseline'){
    echo "[5/10] Criando backup-base novo...\n";
    try{
        $svc=new BackupService();
        $b=$svc->create('baseline-pre-homologacao');
        $id=(int)($b['id']??0);
        if($id!==1)throw new RuntimeException("Backup-base deveria receber ID 1; recebeu {$id}.");
        $q=$pdo->prepare("SELECT * FROM backups WHERE id=1");$q->execute();$row=$q->fetch(PDO::FETCH_ASSOC);
        if(!$row)throw new RuntimeException('Backup-base ID 1 não encontrado.');
        $restore=$svc->testRestore($row,masterId($pdo));
        $ver=(int)$pdo->query("SELECT id FROM backup_verifications WHERE backup_id=1 ORDER BY id DESC LIMIT 1")->fetchColumn();
        if($ver!==1)throw new RuntimeException("Verification deveria receber ID 1; recebeu {$ver}.");
        echo "[OK] Backup-base ID 1; verification ID 1; restore ".(int)($restore['tables']??0)." tabela(s).\n";
        exit(0);
    }catch(Throwable $e){hfail('Backup-base falhou: '.$e->getMessage());}
}

if($mode==='finish'){
    echo "[6/10] Limpando logs gerados durante a manutenção...\n";
    $logs=array_unique(array_merge([$root.'/error_log',$root.'/storage/logs/app.log'],glob($root.'/storage/logs/*.log')?:[]));
    foreach($logs as $f)if(is_file($f))@file_put_contents($f,'',LOCK_EX);
    try{$pdo->prepare("DELETE FROM operational_incidents WHERE category='application' AND title='Erros recentes da aplicação'")->execute();}catch(Throwable){}
    $s=stateRead($state);
    if(!empty($s['backup_temp'])&&is_file($s['backup_temp']))@unlink($s['backup_temp']);
    @unlink($state);
    echo "[OK] Logs zerados, incidente antigo removido e backup temporário descartado.\n";
    exit(0);
}

if($mode==='state'){
    $s=stateRead($state);
    echo json_encode($s,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES)."\n";
    exit(0);
}

hfail('Uso: php tools/pre-homologation-backup-helper.php prepare|baseline|finish|state');
