<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);$payload=$root.'/patches/applanner-limpeza-rf-demo-isolada-v1/payload';$dry=in_array('--dry-run',$argv,true);
function fail(string $m):never{fwrite(STDERR,"[ERRO] {$m}\n");exit(1);}
function runPhp(string $f,array $args=[]):array{$cmd=escapeshellarg(PHP_BINARY).' '.escapeshellarg($f);foreach($args as $a)$cmd.=' '.escapeshellarg($a);$o=[];$c=0;@exec($cmd.' 2>&1',$o,$c);return[$c,implode("\n",$o)];}
function copyTree(string $src,string $dst,array &$copied):void{$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($src,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::SELF_FIRST);foreach($it as $f){$rel=substr($f->getPathname(),strlen($src)+1);$to=$dst.'/'.$rel;if($f->isDir()){if(!is_dir($to))@mkdir($to,0750,true);continue;}if(!is_dir(dirname($to)))@mkdir(dirname($to),0750,true);if(!copy($f->getPathname(),$to))fail('Falha copiando '.$rel);$copied[]=$rel;}}
if(!is_dir($payload))fail('Payload não encontrado. Extraia o ZIP na raiz public_html.');
[$pc,$po]=runPhp($root.'/tools/preflight-clean-homologation.php');echo $po."\n";if($pc!==0)exit($pc);
[$dc,$do]=runPhp($root.'/tools/cleanup-production-data.php');echo "\n".$do."\n";if($dc!==0)exit($dc);
if($dry){echo "\nDRY RUN: OK. Nenhuma alteração foi feita.\n";echo "A aplicação criará backup+restore test, migration 044, limpeza, demo isolada e smoke tests.\n";exit(0);}

require $root.'/app/Core/bootstrap.php';
$pdo=\App\Core\Database::connection();

echo "\n[1/8] Backup obrigatório antes da limpeza...\n";
try{$backup=(new \App\Services\BackupService())->create('clean-rf-demo-isolated');}catch(Throwable $e){fail('Backup falhou: '.$e->getMessage());}
echo "[OK] Backup: ".($backup['name']??$backup['path']??$backup['id']??'criado')."\n";

echo "[2/8] Testando restauração isolada...\n";
try{
 $q=$pdo->prepare("SELECT * FROM backups WHERE id=:id");$q->execute(['id'=>(int)($backup['id']??0)]);$row=$q->fetch();if(!$row)throw new RuntimeException('registro de backup ausente');
 $uid=(int)$pdo->query("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.slug='master' ORDER BY u.id LIMIT 1")->fetchColumn();
 if(!$uid)throw new RuntimeException('usuário master não localizado');
 $r=(new \App\Services\BackupService())->testRestore($row,$uid);echo "[OK] Restore test: ".(int)($r['tables']??0)." tabela(s)\n";
}catch(Throwable $e){fail('Teste de restauração falhou: '.$e->getMessage());}

$stamp=date('Ymd-His');$codeBackup=$root.'/storage/update-backups/clean-rf-demo-'.$stamp.'/files';
$changed=[];
$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload,FilesystemIterator::SKIP_DOTS));
foreach($it as $f){if(!$f->isFile())continue;$rel=substr($f->getPathname(),strlen($payload)+1);$from=$root.'/'.$rel;if(is_file($from)){$to=$codeBackup.'/'.$rel;if(!is_dir(dirname($to)))@mkdir(dirname($to),0750,true);copy($from,$to);}$changed[]=$rel;}
@file_put_contents(dirname($codeBackup).'/MANIFEST.txt',"Backup DB id=".($backup['id']??'?')."\n".implode("\n",$changed)."\n",LOCK_EX);

echo "[3/8] Instalando migration 044...\n";
$migSrc=$payload.'/database/migrations/044_demo_isolation.sql';$migDst=$root.'/database/migrations/044_demo_isolation.sql';
if(!copy($migSrc,$migDst))fail('Falha copiando migration 044.');
try{\App\Core\Migrator::run($pdo,$root.'/database/migrations');}catch(Throwable $e){fail('Migration 044 falhou: '.$e->getMessage());}
echo "[OK] Migration 044 aplicada.\n";

echo "[4/8] Copiando código de isolamento...\n";
$copied=[];copyTree($payload,$root,$copied);
foreach($copied as $rel)if(str_ends_with($rel,'.php')){$o=[];$c=0;@exec(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($root.'/'.$rel).' 2>&1',$o,$c);if($c!==0)fail('Lint falhou em '.$rel.': '.implode(' ',$o));}
echo "[OK] Código copiado e lint aprovado.\n";

echo "[5/8] Limpando tenants/testes e preservando RF Films...\n";
[$cc,$co]=runPhp($root.'/tools/cleanup-production-data.php',['--apply']);echo $co."\n";if($cc!==0)fail('Limpeza falhou.');

echo "[6/8] Criando nova demonstração isolada...\n";
[$dc,$do]=runPhp($root.'/tools/demo-auto-company.php',['install']);echo $do."\n";if($dc!==0)fail('Criação da demo falhou.');

echo "[7/8] Smoke tests...\n";
foreach(['tests/homologation_clean_smoke.php','tests/demo_commercial_smoke.php','tests/rc1_regression_static.php'] as $test){
 [$tc,$to]=runPhp($root.'/'.$test);echo $to."\n";if($tc!==0)fail('Teste falhou: '.$test);
}

echo "[8/8] GO técnico atualizado...\n";
[$gc,$go]=runPhp($root.'/tools/rc1-go-live.php',['--external']);echo $go."\n";

echo "\nPATCH LIMPEZA RF + DEMO ISOLADA INSTALADO.\n";
echo "Backup DB id: ".($backup['id']??'?')."\n";
echo "Backup de código: ".dirname($codeBackup)."\n";
echo "A demo não conta em métricas, billing ou automações de homologação.\n";
echo "Os aceites RC1 foram resetados: execute os testes reais antes de marcar --pass.\n";
