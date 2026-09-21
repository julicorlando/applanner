<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
$payload=$root.'/patches/applanner-arena-v2/payload';
$dry=in_array('--dry-run',$argv,true);
$fail=static function(string $m): never { fwrite(STDERR,"[ERRO] {$m}\n"); exit(1); };
$run=static function(string $cmd,array &$out=null): int { $o=[];$c=0;exec($cmd.' 2>&1',$o,$c); if($out!==null)$out=$o; return $c; };
$copy=static function(string $src,string $dst): void { $d=dirname($dst); if(!is_dir($d)&&!mkdir($d,0755,true)&&!is_dir($d))throw new RuntimeException('Falha ao criar '.$d); if(!copy($src,$dst))throw new RuntimeException('Falha ao copiar '.$dst); };

$pre=[];$preCode=$run(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tools/preflight-arena-v2.php'),$pre);
echo implode("\n",$pre)."\n";
if($preCode!==0)$fail('Preflight falhou. Corrija os erros antes de instalar.');

$files=[];
$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($payload,FilesystemIterator::SKIP_DOTS));
foreach($it as $f){if(!$f->isFile())continue;$rel=str_replace('\\','/',substr($f->getPathname(),strlen($payload)+1));$files[$rel]=$f->getPathname();}
ksort($files);
if($dry){ echo "\n[OK] DRY RUN: payload validado; migrations não executadas; arquivos não alterados.\nDRY RUN: OK.\n"; exit(0); }

$backupRoot=$root.'/storage/update-backups';
$stamp=date('Ymd-His'); $backupDir=$backupRoot.'/arena-v2-'.$stamp;
if(!is_dir($backupDir)&&!mkdir($backupDir,0750,true)&&!is_dir($backupDir))$fail('Não foi possível criar '.$backupDir);
$manifest=['patch'=>'APPLANNER_ARENA_V2_COMPLETO','created_at'=>date(DATE_ATOM),'backup_dir'=>$backupDir,'files'=>[]];

try{
  // Backup de TODOS os arquivos que o payload poderá alterar.
  foreach($files as $rel=>$src){
    $dst=$root.'/'.$rel; $exists=is_file($dst);
    $entry=['path'=>$rel,'existed'=>$exists,'sha256_before'=>$exists?hash_file('sha256',$dst):null,'sha256_payload'=>hash_file('sha256',$src)];
    if($exists)$copy($dst,$backupDir.'/files/'.$rel);
    $manifest['files'][]=$entry;
  }
  file_put_contents($backupDir.'/manifest.json',json_encode($manifest,JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR));

  // FASE 1: somente migrations. Código novo ainda não é liberado.
  foreach(['database/migrations/037_applanner_arena_v1.sql','database/migrations/038_applanner_arena_v2_complete.sql'] as $rel) $copy($files[$rel],$root.'/'.$rel);
  echo "[OK] Migrations preparadas\n";

  // Executa migrator nativo sem carregar o bootstrap HTTP/handler de página.
  spl_autoload_register(static function(string $class) use($root): void {
    $prefix='App\\'; if(!str_starts_with($class,$prefix))return;
    $f=$root.'/app/'.str_replace('\\','/',substr($class,strlen($prefix))).'.php'; if(is_file($f))require_once $f;
  });
  $pdo=\App\Core\Database::connection();
  \App\Core\Migrator::run($pdo,$root.'/database/migrations');
  $applied=$pdo->query("SELECT migration FROM migrations WHERE migration IN ('037_applanner_arena_v1.sql','038_applanner_arena_v2_complete.sql')")->fetchAll(PDO::FETCH_COLUMN);
  if(!in_array('037_applanner_arena_v1.sql',$applied,true)||!in_array('038_applanner_arena_v2_complete.sql',$applied,true)) throw new RuntimeException('Migrations 037/038 não foram registradas após execução.');
  echo "[OK] Migrations 037 e 038 aplicadas/confirmadas\n";

  // FASE 2: somente depois do schema pronto, libera os demais arquivos.
  foreach($files as $rel=>$src){ if(str_starts_with($rel,'database/migrations/'))continue; $copy($src,$root.'/'.$rel); }
  echo "[OK] Arquivos da aplicação atualizados\n";

  // Lint pós-cópia nos PHP efetivamente instalados.
  foreach($files as $rel=>$src){
    if(!str_ends_with(strtolower($rel),'.php'))continue;
    $o=[];$c=$run(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($root.'/'.$rel),$o);
    if($c!==0)throw new RuntimeException('Lint pós-instalação falhou em '.$rel.': '.implode(' ',$o));
  }
  echo "[OK] Lint pós-instalação aprovado\n";

  $smoke=[];$smokeCode=$run(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tests/arena_v2_smoke.php'),$smoke);
  if($smokeCode!==0)throw new RuntimeException('Smoke test falhou: '.implode(' | ',$smoke));
  echo implode("\n",$smoke)."\n";
  $unit=[];$unitCode=$run(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tests/mercadopago_card_provider_unit.php'),$unit);
  if($unitCode!==0)throw new RuntimeException('Teste unitário Mercado Pago cartão falhou: '.implode(' | ',$unit));
  echo implode("\n",$unit)."\n";

  $updates=$root.'/storage/updates'; if(!is_dir($updates))@mkdir($updates,0750,true);
  file_put_contents($updates.'/arena-v2.json',json_encode(['patch'=>'APPLANNER_ARENA_V2_COMPLETO','installed_at'=>date(DATE_ATOM),'backup_dir'=>$backupDir],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));
  echo "\nPATCH APPLANNER ARENA V2 COMPLETO INSTALADO.\nBackup: {$backupDir}\n";
}catch(Throwable $e){
  fwrite(STDERR,"[ERRO] Instalação interrompida: {$e->getMessage()}\n");
  fwrite(STDERR,"Restaurando arquivos a partir de {$backupDir} ...\n");
  foreach(array_reverse($manifest['files']) as $entry){
    $rel=$entry['path'];$dst=$root.'/'.$rel;
    if($entry['existed']){ $src=$backupDir.'/files/'.$rel; if(is_file($src))$copy($src,$dst); }
    elseif(is_file($dst))@unlink($dst);
  }
  fwrite(STDERR,"Arquivos restaurados. Alterações incrementais de banco já confirmadas não são apagadas para preservar dados; o schema V2 é aditivo e o código anterior ignora colunas/tabelas extras.\n");
  exit(1);
}
