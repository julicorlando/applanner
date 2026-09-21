<?php
namespace App\Services;
use App\Core\Database;
final class BackupService
{
 public function create(string $reason='manual'):array
 {
  $pdo=Database::connection();$cfg=$pdo->query('SELECT * FROM platform_operation_settings WHERE id=1')->fetch()?:[];$dir=$this->directory();
  if(!is_dir($dir)&&!mkdir($dir,0750,true)&&!is_dir($dir))throw new \RuntimeException('Pasta privada indisponível.');
  $stamp=date('Ymd-His').'-'.bin2hex(random_bytes(3));$sql=$dir.'/database-'.$stamp.'.sql';$scope=!empty($cfg['backup_include_uploads'])?'database_uploads':'database';
  $pdo->prepare("INSERT INTO backups(type,scope,status,destination,path,started_at)VALUES('database',:scope,'running','local',:path,NOW())")->execute(['scope'=>$scope,'path'=>$sql]);$id=(int)$pdo->lastInsertId();
  try{
   $this->dump($pdo,$sql);$path=$scope==='database_uploads'?$this->bundle($sql,$stamp):$sql;$encrypted=0;$method=null;
   if(!empty($cfg['backup_encrypt'])){$path=$this->encrypt($path);$encrypted=1;$method='AES-256-GCM';}
   $size=(int)(filesize($path)?:0);$hash=hash_file('sha256',$path);$days=max(1,(int)($cfg['backup_retention_days']??30));
   $pdo->prepare("UPDATE backups SET status='completed',path=:path,size_bytes=:size,checksum_sha256=:hash,encrypted=:enc,encryption_method=:method,completed_at=NOW(),expires_at=DATE_ADD(NOW(),INTERVAL :days DAY) WHERE id=:id")->execute(['path'=>$path,'size'=>$size,'hash'=>$hash,'enc'=>$encrypted,'method'=>$method,'days'=>$days,'id'=>$id]);$this->purgeExpired($pdo);
   return ['id'=>$id,'name'=>basename($path),'path'=>$path,'size'=>$size,'reason'=>$reason];
  }catch(\Throwable $e){foreach(glob($dir.'/*'.$stamp.'*')?:[] as $f)if(is_file($f))@unlink($f);$pdo->prepare("UPDATE backups SET status='failed',error_message=:e,completed_at=NOW() WHERE id=:id")->execute(['e'=>mb_substr($e->getMessage(),0,500),'id'=>$id]);throw $e;}
 }
 public function testRestore(array $backup,int $user):array
 {
  $pdo=Database::connection();$original=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();$file=realpath((string)$backup['path']);
  if(!$file||!is_file($file)||!hash_equals((string)$backup['checksum_sha256'],hash_file('sha256',$file)))throw new \RuntimeException('Arquivo ausente ou checksum divergente.');
  $work=sys_get_temp_dir().'/applanner-restore-'.bin2hex(random_bytes(6));if(!mkdir($work,0700,true))throw new \RuntimeException('Área isolada indisponível.');$db='applanner_restore_'.date('YmdHis').'_'.bin2hex(random_bytes(2));
  try{
   $source=!empty($backup['encrypted'])?$this->decrypt($file,$work):$file;$sqlFile=$source;
   if(str_ends_with($source,'.zip')){$z=new \ZipArchive();if($z->open($source)!==true)throw new \RuntimeException('Pacote inválido.');$z->extractTo($work,'database.sql');$z->close();$sqlFile=$work.'/database.sql';}
   try{
    $pdo->exec("CREATE DATABASE `{$db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");$pdo->exec("USE `{$db}`");$this->importSql($pdo,$sqlFile);
    $tables=(int)$pdo->query('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='.$pdo->quote($db))->fetchColumn();if($tables<1)throw new \RuntimeException('Nenhuma tabela restaurada.');
    $pdo->exec("USE `{$original}`");$pdo->exec("DROP DATABASE `{$db}`");
    $details=$tables.' tabela(s) restaurada(s) em base temporária e ambiente removido.';$restoredRef=$db;
   }catch(\Throwable $dbError){
    try{$pdo->exec("USE `{$original}`");$pdo->exec("DROP DATABASE IF EXISTS `{$db}`");}catch(\Throwable){}
    if(!$this->isDatabaseCreatePermissionError($dbError))throw $dbError;
    $fallback=$this->testRestoreWithPrefixedTables($pdo,$original,$sqlFile);
    $tables=(int)$fallback['tables'];$restoredRef=(string)$fallback['reference'];$details=$fallback['details'].' Motivo do fallback: sem permissão CREATE DATABASE.';
   }
   $pdo->prepare("INSERT INTO backup_verifications(backup_id,verification_type,status,details,restored_database,verified_by,verified_at,completed_at)VALUES(:b,'restore','passed',:d,:db,:u,NOW(),NOW())")->execute(['b'=>$backup['id'],'d'=>$details,'db'=>$restoredRef,'u'=>$user]);return ['tables'=>$tables,'database'=>$restoredRef];
  }catch(\Throwable $e){
   try{$pdo->exec("USE `{$original}`");$pdo->exec("DROP DATABASE IF EXISTS `{$db}`");}catch(\Throwable){}
   $pdo->prepare("INSERT INTO backup_verifications(backup_id,verification_type,status,details,verified_by,verified_at,completed_at)VALUES(:b,'restore','failed',:d,:u,NOW(),NOW())")->execute(['b'=>$backup['id'],'d'=>mb_substr($e->getMessage(),0,500),'u'=>$user]);throw $e;
  }finally{$this->removeTree($work);}
 }
 private function testRestoreWithPrefixedTables(\PDO $pdo,string $database,string $sqlFile):array
 {
  $raw=file_get_contents($sqlFile);if($raw===false||trim($raw)==='')throw new \RuntimeException('SQL de restauração indisponível para fallback.');
  preg_match_all('/(?:DROP TABLE IF EXISTS|CREATE TABLE|INSERT INTO)\s+`([^`]+)`/i',$raw,$matches);
  $tables=array_values(array_unique($matches[1]??[]));if(!$tables)throw new \RuntimeException('Nenhuma tabela identificada no SQL de backup.');
  $prefix='rc1rt_'.bin2hex(random_bytes(4)).'_';
  foreach($tables as $table){
   $safe=$prefix.$table;
   $raw=preg_replace('/(DROP TABLE IF EXISTS\s+)`'.preg_quote($table,'/').'`/i','$1`'.$safe.'`',$raw)??$raw;
   $raw=preg_replace('/(CREATE TABLE\s+)`'.preg_quote($table,'/').'`/i','$1`'.$safe.'`',$raw)??$raw;
   $raw=preg_replace('/(INSERT INTO\s+)`'.preg_quote($table,'/').'`/i','$1`'.$safe.'`',$raw)??$raw;
   $raw=preg_replace('/(REFERENCES\s+)`'.preg_quote($table,'/').'`/i','$1`'.$safe.'`',$raw)??$raw;
  }
  $raw=preg_replace_callback('/CONSTRAINT\s+`([^`]+)`/i',function(array $m)use($prefix):string{
   return 'CONSTRAINT `'.substr($prefix.'fk_'.substr(hash('sha256',$m[1]),0,24),0,60).'`';
  },$raw)??$raw;
  $tmp=tempnam(sys_get_temp_dir(),'applanner-rc1-restore-');if($tmp===false)throw new \RuntimeException('Não foi possível criar SQL temporário.');
  file_put_contents($tmp,$raw,LOCK_EX);
  try{
   $pdo->exec("USE `{$database}`");$pdo->exec('SET FOREIGN_KEY_CHECKS=0');$this->importSql($pdo,$tmp);
   $q=$pdo->prepare("SELECT table_name FROM information_schema.tables WHERE table_schema=? AND table_name LIKE ? ESCAPE '\\\\'");$q->execute([$database,$this->escapeLike($prefix).'%']);$created=$q->fetchAll(\PDO::FETCH_COLUMN)?:[];
   $count=count($created);if($count<1)throw new \RuntimeException('Fallback não restaurou tabelas temporárias.');
   return ['tables'=>$count,'reference'=>'same-db-prefix:'.$prefix,'details'=>$count.' tabela(s) restaurada(s) com prefixo temporário no banco atual e removidas ao final.'];
  }finally{
   try{
    $pdo->exec("USE `{$database}`");$pdo->exec('SET FOREIGN_KEY_CHECKS=0');
    $q=$pdo->prepare("SELECT table_name FROM information_schema.tables WHERE table_schema=? AND table_name LIKE ? ESCAPE '\\\\'");$q->execute([$database,$this->escapeLike($prefix).'%']);
    foreach($q->fetchAll(\PDO::FETCH_COLUMN)?:[] as $table){if(str_starts_with($table,$prefix))$pdo->exec('DROP TABLE IF EXISTS `'.str_replace('`','``',$table).'`');}
    $pdo->exec('SET FOREIGN_KEY_CHECKS=1');
   }catch(\Throwable){}
   @unlink($tmp);
  }
 }
 private function isDatabaseCreatePermissionError(\Throwable $e):bool
 {
  $m=strtolower($e->getMessage());return str_contains($m,'access denied')||str_contains($m,'create command denied')||str_contains($m,'permission')||str_contains($m,'privilege')||str_contains($m,'1044')||str_contains($m,'1045')||str_contains($m,'42000');
 }
 private function escapeLike(string $value):string{return str_replace(['\\','%','_'],['\\\\','\\%','\\_'],$value);}
 private function importSql(\PDO $pdo,string $file):void
 {
  $h=fopen($file,'rb');if(!$h)throw new \RuntimeException('SQL indisponível.');$statement='';
  while(($line=fgets($h))!==false){$trim=trim($line);if($trim===''||str_starts_with($trim,'--'))continue;$statement.=$line;if(str_ends_with(rtrim($line),';')){$pdo->exec($statement);$statement='';}}
  fclose($h);if(trim($statement)!=='')throw new \RuntimeException('SQL incompleto.');
 }
 private function dump(\PDO $pdo,string $path):void
 {
  $h=fopen($path,'xb');if(!$h)throw new \RuntimeException('Não foi possível criar o SQL.');fwrite($h,"SET FOREIGN_KEY_CHECKS=0;\nSET NAMES utf8mb4;\n");
  foreach($pdo->query('SHOW TABLES')->fetchAll(\PDO::FETCH_COLUMN) as $table){if(!preg_match('/^[a-zA-Z0-9_]+$/',$table))continue;$create=$pdo->query("SHOW CREATE TABLE `{$table}`")->fetch(\PDO::FETCH_NUM);if(!$create)continue;fwrite($h,"DROP TABLE IF EXISTS `{$table}`;\n{$create[1]};\n");foreach($pdo->query("SELECT * FROM `{$table}`",\PDO::FETCH_ASSOC) as $row){$v=array_map(fn($x)=>$x===null?'NULL':$pdo->quote((string)$x),array_values($row));fwrite($h,"INSERT INTO `{$table}` VALUES(".implode(',',$v).");\n");}}
  fwrite($h,"SET FOREIGN_KEY_CHECKS=1;\n");fclose($h);chmod($path,0640);
 }
 private function bundle(string $sql,string $stamp):string
 {
  if(!class_exists('ZipArchive'))throw new \RuntimeException('Extensão ZIP necessária para incluir uploads.');$out=dirname($sql).'/backup-'.$stamp.'.zip';$z=new \ZipArchive();if($z->open($out,\ZipArchive::CREATE|\ZipArchive::EXCL)!==true)throw new \RuntimeException('Pacote não pôde ser criado.');$z->addFile($sql,'database.sql');$root=dirname(__DIR__,2);
  foreach(['public/uploads','storage/uploads'] as $rel){$base=$root.'/'.$rel;if(!is_dir($base))continue;$it=new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($base,\FilesystemIterator::SKIP_DOTS));foreach($it as $f)if($f->isFile()&&!$f->isLink())$z->addFile($f->getPathname(),'uploads/'.$rel.'/'.substr($f->getPathname(),strlen($base)+1));}
  $z->close();@unlink($sql);chmod($out,0640);return $out;
 }
 private function encrypt(string $path):string{$key=$this->key();$data=file_get_contents($path);if($data===false)throw new \RuntimeException('Leitura falhou.');$iv=random_bytes(12);$tag='';$cipher=openssl_encrypt($data,'aes-256-gcm',$key,OPENSSL_RAW_DATA,$iv,$tag);if($cipher===false)throw new \RuntimeException('Criptografia falhou.');$out=$path.'.enc';file_put_contents($out,'APB1'.$iv.$tag.$cipher,LOCK_EX);chmod($out,0640);@unlink($path);return $out;}
 private function decrypt(string $file,string $work):string
 {
  $raw=file_get_contents($file);if($raw===false||substr($raw,0,4)!=='APB1')throw new \RuntimeException('Formato criptografado inválido.');$plain=false;
  foreach($this->keyCandidates() as $key){$plain=openssl_decrypt(substr($raw,32),'aes-256-gcm',$key,OPENSSL_RAW_DATA,substr($raw,4,12),substr($raw,16,16));if($plain!==false)break;}
  if($plain===false)throw new \RuntimeException('Descriptografia falhou: nenhuma APP_KEY compatível com este backup.');$out=$work.(str_ends_with($file,'.zip.enc')?'/backup.zip':'/database.sql');file_put_contents($out,$plain,LOCK_EX);return $out;
 }
 private function key():string{$keys=$this->keyCandidates();if(!$keys)throw new \RuntimeException('APP_KEY não configurada. Defina APP_KEY no ambiente ou config/app.php.');return $keys[0];}
 private function keyCandidates():array
 {
  $keys=[];$seen=[];
  $add=function(string $key)use(&$keys,&$seen):void{if(strlen($key)!==32)return;$id=bin2hex($key);if(isset($seen[$id]))return;$seen[$id]=true;$keys[]=$key;};
  $env=(string)(getenv('APP_KEY')?:'');
  if($env!==''){
   // Compatibilidade com o BackupService anterior: getenv(APP_KEY) era sempre SHA-256.
   $add(hash('sha256',$env,true));
   $candidate=str_starts_with($env,'base64:')?substr($env,7):$env;$decoded=base64_decode($candidate,true);if($decoded!==false)$add($decoded);
  }
  $appFile=dirname(__DIR__,2).'/config/app.php';
  if(is_file($appFile)){
   $app=require $appFile;$configured=(string)($app['app_key']??'');
   if($configured!==''){$candidate=str_starts_with($configured,'base64:')?substr($configured,7):$configured;$decoded=base64_decode($candidate,true);if($decoded!==false)$add($decoded);$add(hash('sha256',$configured,true));}
  }
  return $keys;
 }
 private function purgeExpired(\PDO $pdo):void{foreach($pdo->query("SELECT id,path FROM backups WHERE expires_at<NOW() AND status='completed'") as $r){if(is_file($r['path']))@unlink($r['path']);$pdo->prepare("UPDATE backups SET status='expired',path='' WHERE id=:id")->execute(['id'=>$r['id']]);}}
 private function removeTree(string $dir):void{if(!is_dir($dir))return;$it=new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($dir,\FilesystemIterator::SKIP_DOTS),\RecursiveIteratorIterator::CHILD_FIRST);foreach($it as $f)$f->isDir()?@rmdir($f->getPathname()):@unlink($f->getPathname());@rmdir($dir);}
 public function directory():string{return dirname(__DIR__,2).'/storage/private/backups';}
}
