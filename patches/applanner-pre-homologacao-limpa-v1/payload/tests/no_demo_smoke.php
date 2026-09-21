<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();$bad=[];

$real=$pdo->query("SELECT id,name,slug FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=0 ORDER BY id")->fetchAll(PDO::FETCH_ASSOC)?:[];
$demo=(int)$pdo->query("SELECT COUNT(*) FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=1")->fetchColumn();
$demoSlug=(int)$pdo->query("SELECT COUNT(*) FROM tenants WHERE slug='auto-prime-demonstracao' OR public_slug='applanner-auto-demo'")->fetchColumn();
$failed=(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='failed'")->fetchColumn();
$backups=(int)$pdo->query("SELECT COUNT(*) FROM backups")->fetchColumn();
$verified=(int)$pdo->query("SELECT COUNT(*) FROM backup_verifications WHERE status='passed'")->fetchColumn();

if(count($real)!==1)$bad[]='esperado exatamente 1 tenant real';
if($real){
  $name=mb_strtolower((string)$real[0]['name']);
  $slug=mb_strtolower((string)$real[0]['slug']);
  if(!(str_contains($name,'rf')&&str_contains($name,'films')) && $slug!=='rf-films')$bad[]='tenant real não é RF Films';
}
if($demo!==0)$bad[]="{$demo} tenant(s) demo";
if($demoSlug!==0)$bad[]='slug da Auto Demo ainda existe';
if($failed!==0)$bad[]="{$failed} job(s) failed";
if($backups!==1)$bad[]="esperado 1 backup-base, encontrado {$backups}";
if($verified<1)$bad[]='backup-base sem verificação aprovada';

$landing=(string)@file_get_contents(dirname(__DIR__).'/app/Views/commercial/landing.php');
$js=(string)@file_get_contents(dirname(__DIR__).'/public/assets/js/index-conversion.js');
if(str_contains($landing,'/auto/applanner-auto-demo')||str_contains($js,'/auto/applanner-auto-demo'))$bad[]='link público da demo ainda presente';

echo "Tenant real: ".($real[0]['name']??'N/D')." | demos={$demo} | failed_jobs={$failed} | backups={$backups} | restore_passed={$verified}\n";
if($bad){foreach($bad as $x)fwrite(STDERR,"[FALHA] {$x}\n");exit(1);}
echo "no demo smoke: OK\n";
