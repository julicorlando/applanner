<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);$payload=$root.'/patches/applanner-pre-homologacao-limpa-v1/payload';$dry=in_array('--dry-run',$argv,true);
function fail(string $m):never{fwrite(STDERR,"[ERRO] {$m}\n");exit(1);}
function runPhp(string $file,array $args=[]):array{$cmd=escapeshellarg(PHP_BINARY).' '.escapeshellarg($file);foreach($args as $a)$cmd.=' '.escapeshellarg($a);$o=[];$c=0;@exec($cmd.' 2>&1',$o,$c);return[$c,implode("\n",$o)];}
function copyTree(string $src,string $dst):void{$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($src,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::SELF_FIRST);foreach($it as $f){$rel=substr($f->getPathname(),strlen($src)+1);$to=$dst.'/'.$rel;if($f->isDir()){if(!is_dir($to))@mkdir($to,0750,true);continue;}if(!is_dir(dirname($to)))@mkdir(dirname($to),0750,true);if(!copy($f->getPathname(),$to))fail('Falha copiando '.$rel);}}
if(!is_dir($payload))fail('Payload não encontrado. Extraia o ZIP na raiz public_html.');

[$pc,$po]=runPhp($payload.'/tools/preflight-pre-homologation-clean.php');echo $po."\n";if($pc!==0)exit($pc);
[$dc,$do]=runPhp($payload.'/tools/pre-homologation-clean.php');echo "\n".$do."\n";if($dc!==0)exit($dc);
if($dry){echo "\nDRY RUN: OK. Nenhuma alteração foi feita.\n";exit(0);}

require $root.'/app/Core/bootstrap.php';
$pdo=\App\Core\Database::connection();
$tmpSafety=sys_get_temp_dir().'/applanner-prehomolog-'.date('Ymd-His').'.zip.enc';
$tmpCode=sys_get_temp_dir().'/applanner-prehomolog-code-'.date('Ymd-His');

echo "\n[1/10] Criando backup temporário de segurança...\n";
try{
 $svc=new \App\Services\BackupService();$safety=$svc->create('pre-homologacao-final-clean');
 $q=$pdo->prepare("SELECT * FROM backups WHERE id=:id");$q->execute(['id'=>(int)$safety['id']]);$row=$q->fetch();
 if(!$row)throw new RuntimeException('registro de backup não encontrado');
 $uid=(int)$pdo->query("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.slug='master' ORDER BY u.id LIMIT 1")->fetchColumn();
 if(!$uid)throw new RuntimeException('Master não localizado');
 $svc->testRestore($row,$uid);
 if(empty($row['path'])||!is_file($row['path']))throw new RuntimeException('arquivo do backup temporário ausente');
 if(!copy($row['path'],$tmpSafety))throw new RuntimeException('não foi possível copiar backup temporário para /tmp');
 echo "[OK] Backup temporário criado, restaurado e copiado para {$tmpSafety}\n";
}catch(Throwable $e){fail('Backup temporário falhou: '.$e->getMessage());}

echo "[2/10] Salvando temporariamente os arquivos que serão alterados...\n";
@mkdir($tmpCode,0700,true);
$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload,FilesystemIterator::SKIP_DOTS));
foreach($it as $f){if(!$f->isFile())continue;$rel=substr($f->getPathname(),strlen($payload)+1);$cur=$root.'/'.$rel;if(is_file($cur)){$to=$tmpCode.'/'.$rel;@mkdir(dirname($to),0700,true);@copy($cur,$to);}}
echo "[OK] Cópia temporária: {$tmpCode}\n";

echo "[3/10] Instalando código de homologação sem demo...\n";
copyTree($payload,$root);
foreach([
 'app/Services/IncidentMonitorService.php','app/Controllers/OperationsCenterController.php',
 'app/Views/commercial/landing.php','tools/rc1-go-live.php','tools/demo-auto-company.php',
 'tools/pre-homologation-clean.php','tools/id-sequence-status.php','tests/no_demo_smoke.php','tests/rc1_regression_static.php'
] as $rel){
 if(str_ends_with($rel,'.php')){$o=[];$c=0;@exec(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($root.'/'.$rel).' 2>&1',$o,$c);if($c!==0)fail('Lint: '.$rel.' '.implode(' ',$o));}
}
echo "[OK] Código copiado e lint aprovado.\n";

echo "[4/10] Removendo demo, históricos e backups antigos...\n";
[$cc,$co]=runPhp($root.'/tools/pre-homologation-clean.php',['--apply']);echo $co."\n";if($cc!==0)fail('Limpeza falhou. Backup temporário mantido em '.$tmpSafety);

echo "[5/10] Criando backup-base novo (sequência deve começar em ID 1)...\n";
try{
 $svc=new \App\Services\BackupService();$base=$svc->create('baseline-pre-homologacao');
 $baseId=(int)($base['id']??0);
 if($baseId!==1)throw new RuntimeException('backup-base deveria receber ID 1, recebeu '.$baseId);
 $q=$pdo->prepare("SELECT * FROM backups WHERE id=:id");$q->execute(['id'=>$baseId]);$row=$q->fetch();
 $uid=(int)$pdo->query("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE r.slug='master' ORDER BY u.id LIMIT 1")->fetchColumn();
 $restore=$svc->testRestore($row,$uid);
 $verId=(int)$pdo->query("SELECT id FROM backup_verifications WHERE backup_id=1 ORDER BY id DESC LIMIT 1")->fetchColumn();
 if($verId!==1)throw new RuntimeException('primeira verificação deveria receber ID 1, recebeu '.$verId);
 echo "[OK] Backup-base ID 1; verificação ID 1; restore ".(int)($restore['tables']??0)." tabela(s).\n";
}catch(Throwable $e){fail('Criação do backup-base falhou: '.$e->getMessage().'. Backup temporário mantido em '.$tmpSafety);}

echo "[6/10] Limpando novamente logs gerados durante a manutenção...\n";
foreach(array_unique(array_merge([$root.'/error_log',$root.'/storage/logs/app.log'],glob($root.'/storage/logs/*.log')?:[])) as $f)if(is_file($f))@file_put_contents($f,'',LOCK_EX);
try{$pdo->prepare("DELETE FROM operational_incidents WHERE category='application' AND title='Erros recentes da aplicação'")->execute();}catch(Throwable){}
echo "[OK] Logs ativos zerados e incidente antigo removido.\n";

echo "[7/10] Validando ausência de demo e base limpa...\n";
foreach(['tests/no_demo_smoke.php','tests/rc1_regression_static.php'] as $test){[$c,$o]=runPhp($root.'/'.$test);echo $o."\n";if($c!==0)fail('Teste falhou: '.$test);}
echo "[OK] Smoke/regression aprovados.\n";

echo "[8/10] Conferindo sequências AUTO_INCREMENT...\n";
[$ic,$io]=runPhp($root.'/tools/id-sequence-status.php');if($ic!==0)fail('Status de IDs falhou.');echo implode("\n",array_slice(explode("\n",$io),0,20))."\n...\n";

echo "[9/10] Executando GO técnico externo...\n";
[$gc,$go]=runPhp($root.'/tools/rc1-go-live.php',['--external']);echo $go."\n";if($gc!==0)echo "[AVISO] GO técnico retornou código {$gc}; revise os avisos/bloqueadores acima.\n";

echo "[10/10] Removendo cópias temporárias de segurança da manutenção...\n";
@unlink($tmpSafety);
if(is_dir($tmpCode)){$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($tmpCode,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::CHILD_FIRST);foreach($it as $f)$f->isDir()?@rmdir($f->getPathname()):@unlink($f->getPathname());@rmdir($tmpCode);}
echo "[OK] Temporários removidos. Permanece apenas o backup-base limpo ID 1.\n";

echo "\nPRE-HOMOLOGAÇÃO LIMPA CONCLUÍDA.\n";
echo "- RF Films preservada\n- Master preservado\n- 0 demos\n- logs antigos limpos\n- backups antigos removidos\n- backup-base novo ID 1\n- verificação de restore ID 1\n- sequências vazias iniciam em 1; tabelas com dados continuam em MAX(id)+1\n";
