<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=rtrim((string)(getenv('APPLANNER_ROOT') ?: dirname(__DIR__)),'/');
if(!is_file($root.'/app/Core/bootstrap.php')){fwrite(STDERR,"[ERRO] bootstrap não encontrado em {$root}/app/Core/bootstrap.php\n");exit(1);}
require $root.'/app/Core/bootstrap.php';
use App\Core\Database;

$pdo=Database::connection();
$apply=in_array('--apply',$argv,true);

function fail(string $m):never{fwrite(STDERR,"[ERRO] {$m}\n");exit(1);}
function qn(string $v):string{return '`'.str_replace('`','``',$v).'`';}
function hasCol(PDO $pdo,string $db,string $t,string $c):bool{
 $q=$pdo->prepare("SELECT 1 FROM information_schema.columns WHERE table_schema=:d AND table_name=:t AND column_name=:c LIMIT 1");
 $q->execute(['d'=>$db,'t'=>$t,'c'=>$c]);return(bool)$q->fetchColumn();
}
function wipeDir(string $dir):void{
 if(!is_dir($dir)){@mkdir($dir,0750,true);return;}
 $it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::CHILD_FIRST);
 foreach($it as $f){$f->isDir()?@rmdir($f->getPathname()):@unlink($f->getPathname());}
}
function resetAuto(PDO $pdo,string $db):array{
 $q=$pdo->prepare("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=:d AND extra LIKE '%auto_increment%' ORDER BY table_name");
 $q->execute(['d'=>$db]);$rows=$q->fetchAll(PDO::FETCH_ASSOC)?:[];$out=[];
 foreach($rows as $r){
   $t=$r['table_name'];$c=$r['column_name'];
   try{
     $max=(int)$pdo->query("SELECT COALESCE(MAX(".qn($c)."),0) FROM ".qn($t))->fetchColumn();
     $next=$max>0?$max+1:1;
     $pdo->exec("ALTER TABLE ".qn($t)." AUTO_INCREMENT=".$next);
     $out[$t]=$next;
   }catch(Throwable $e){$out[$t]='erro: '.$e->getMessage();}
 }
 return $out;
}

$db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
$real=$pdo->query("SELECT id,name,slug FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=0 ORDER BY id")->fetchAll(PDO::FETCH_ASSOC)?:[];
$demo=$pdo->query("SELECT id,name,slug,public_slug FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=1 ORDER BY id")->fetchAll(PDO::FETCH_ASSOC)?:[];
if(count($real)!==1)fail('Esperado exatamente um tenant real antes da limpeza.');
$rf=$real[0];$name=mb_strtolower((string)$rf['name']);if(!((str_contains($name,'rf')&&str_contains($name,'films'))||$rf['slug']==='rf-films'))fail('Tenant real não identificado como RF Films.');
if(count($demo)<1)fail('Nenhum tenant demo localizado para remoção.');

$backupCount=(int)$pdo->query("SELECT COUNT(*) FROM backups")->fetchColumn();
$verificationCount=(int)$pdo->query("SELECT COUNT(*) FROM backup_verifications")->fetchColumn();
$appInc=(int)$pdo->query("SELECT COUNT(*) FROM operational_incidents WHERE category='application' AND title='Erros recentes da aplicação'")->fetchColumn();
$homRuns=(int)$pdo->query("SELECT COUNT(*) FROM homologation_runs")->fetchColumn();

echo "APPLANNER - PRE-HOMOLOGAÇÃO LIMPA\n";
echo "=================================\n";
echo "PRESERVAR: tenant={$rf['id']} | {$rf['name']} | {$rf['slug']}\n";
echo "DEMOS A REMOVER: ".count($demo)."\n";
foreach($demo as $t)echo "  id={$t['id']} | {$t['name']} | slug={$t['slug']} | public={$t['public_slug']}\n";
echo "Backups antigos: {$backupCount} | verificações: {$verificationCount}\n";
echo "Incidente 'Erros recentes da aplicação': {$appInc}\n";
echo "Homologações antigas: {$homRuns}\n";
echo "Regra de IDs: tabelas vazias => próximo ID 1; tabelas com dados => MAX(id)+1. IDs existentes NÃO serão renumerados.\n";

if(!$apply){
 echo "\nDRY RUN: nenhuma alteração realizada.\n";
 exit(0);
}

// Snapshot RF
$q=$pdo->prepare("SELECT table_name FROM information_schema.columns WHERE table_schema=:d AND column_name='tenant_id' ORDER BY table_name");
$q->execute(['d'=>$db]);$tenantTables=$q->fetchAll(PDO::FETCH_COLUMN)?:[];$baseline=[];
foreach($tenantTables as $t){try{$s=$pdo->prepare("SELECT COUNT(*) FROM ".qn($t)." WHERE tenant_id=:id");$s->execute(['id'=>$rf['id']]);$baseline[$t]=(int)$s->fetchColumn();}catch(Throwable){}}

$demoIds=array_map(fn($x)=>(int)$x['id'],$demo);
$pdo->beginTransaction();
try{
 $pdo->exec('SET FOREIGN_KEY_CHECKS=0');
 foreach($tenantTables as $t){
   $marks=implode(',',array_fill(0,count($demoIds),'?'));
   $pdo->prepare("DELETE FROM ".qn($t)." WHERE tenant_id IN ($marks)")->execute($demoIds);
 }
 // Other direct tenant references without tenant_id
 $fk=$pdo->prepare("SELECT table_name,column_name FROM information_schema.key_column_usage WHERE table_schema=:d AND referenced_table_schema=:d2 AND referenced_table_name='tenants' AND column_name<>'tenant_id'");
 $fk->execute(['d'=>$db,'d2'=>$db]);
 foreach($fk->fetchAll(PDO::FETCH_ASSOC) as $r){
   if(hasCol($pdo,$db,$r['table_name'],'tenant_id'))continue;
   $marks=implode(',',array_fill(0,count($demoIds),'?'));
   $pdo->prepare("DELETE FROM ".qn($r['table_name'])." WHERE ".qn($r['column_name'])." IN ($marks)")->execute($demoIds);
 }
 $marks=implode(',',array_fill(0,count($demoIds),'?'));
 $pdo->prepare("DELETE FROM tenants WHERE id IN ($marks)")->execute($demoIds);

 // Orphan cleanup, protecting RF-owned rows
 $fks=$pdo->prepare("SELECT table_name,column_name,referenced_table_name,referenced_column_name FROM information_schema.key_column_usage WHERE table_schema=:d AND referenced_table_schema=:d2 AND referenced_table_name IS NOT NULL ORDER BY table_name,constraint_name,ordinal_position");
 $fks->execute(['d'=>$db,'d2'=>$db]);$fkRows=$fks->fetchAll(PDO::FETCH_ASSOC)?:[];
 for($round=0;$round<8;$round++){
   $removed=0;
   foreach($fkRows as $r){
     if($r['table_name']===$r['referenced_table_name'])continue;
     $guard=hasCol($pdo,$db,$r['table_name'],'tenant_id')?" AND (c.tenant_id IS NULL OR c.tenant_id<>".(int)$rf['id'].")":"";
     $sql="DELETE c FROM ".qn($r['table_name'])." c LEFT JOIN ".qn($r['referenced_table_name'])." p ON c.".qn($r['column_name'])."=p.".qn($r['referenced_column_name'])." WHERE c.".qn($r['column_name'])." IS NOT NULL AND p.".qn($r['referenced_column_name'])." IS NULL".$guard;
     try{$removed+=(int)$pdo->exec($sql);}catch(Throwable){}
   }
   if($removed===0)break;
 }

 // Validate RF counts
 foreach($baseline as $t=>$before){
   $s=$pdo->prepare("SELECT COUNT(*) FROM ".qn($t)." WHERE tenant_id=:id");$s->execute(['id'=>$rf['id']]);$after=(int)$s->fetchColumn();
   if($before!==$after)throw new RuntimeException("RF Films alterada em {$t}: antes={$before}, depois={$after}");
 }

 // Clean application warning/history only
 $pdo->prepare("DELETE FROM operational_incidents WHERE category='application' AND title='Erros recentes da aplicação'")->execute();
 $pdo->exec("DELETE FROM homologation_runs");

 $pdo->exec('SET FOREIGN_KEY_CHECKS=1');
 $pdo->commit();
}catch(Throwable $e){
 if($pdo->inTransaction())$pdo->rollBack();
 try{$pdo->exec('SET FOREIGN_KEY_CHECKS=1');}catch(Throwable){}
 fail('Limpeza de dados cancelada: '.$e->getMessage());
}

// Remove old managed backup files/records
$paths=[];
try{$paths=$pdo->query("SELECT path FROM backups WHERE path IS NOT NULL AND path<>''")->fetchAll(PDO::FETCH_COLUMN)?:[];}catch(Throwable){}
foreach($paths as $p){
 $rp=realpath((string)$p);
 if($rp && str_starts_with($rp,$root.'/storage/'))@unlink($rp);
}
$pdo->exec("DELETE FROM backup_verifications");
$pdo->exec("DELETE FROM backups");
foreach([$root.'/storage/private/backups',$root.'/storage/update-backups',$root.'/storage/backups'] as $dir)wipeDir($dir);

// Reset acceptance + old generated reports/logs
@unlink($root.'/storage/private/rc1-acceptance.json');
foreach(glob($root.'/storage/logs/rc1-go-live-*')?:[] as $f)@unlink($f);
foreach(glob($root.'/storage/logs/auditoria-applanner-*')?:[] as $f)@unlink($f);

// Truncate log files, preserving permissions/inodes
$logs=[$root.'/error_log',$root.'/storage/logs/app.log'];
foreach(glob($root.'/storage/logs/*.log')?:[] as $f)$logs[]=$f;
foreach(array_unique($logs) as $f){
 if(is_file($f))@file_put_contents($f,'',LOCK_EX);
}

// Remove demo recreator legacy artifacts if present; installer will overwrite tool with disabled version afterwards.
@unlink($root.'/tests/demo_commercial_smoke.php');

// Safe AUTO_INCREMENT normalization
$resets=resetAuto($pdo,$db);
$emptyToOne=count(array_filter($resets,fn($v)=>$v===1));
echo "\n[OK] Demo(s) removida(s): ".count($demo)."\n";
echo "[OK] RF Films preservada em ".count($baseline)." tabela(s) tenant-scoped.\n";
echo "[OK] Backups antigos e verificações removidos.\n";
echo "[OK] Logs e incidente antigo da aplicação limpos.\n";
echo "[OK] Histórico de homologação anterior removido.\n";
echo "[OK] AUTO_INCREMENT normalizado em ".count($resets)." tabela(s); {$emptyToOne} tabela(s) vazia(s) começarão em ID 1.\n";
