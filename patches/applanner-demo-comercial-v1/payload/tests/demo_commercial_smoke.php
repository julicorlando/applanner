<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Core\Database;
$checks=[];$ok=function(string $name,bool $v,string $detail='')use(&$checks){$checks[]=[$name,$v,$detail];};
$pdo=Database::connection();
$q=$pdo->prepare("SELECT id,public_slug,category FROM tenants WHERE slug='auto-prime-demonstracao' LIMIT 1");$q->execute();$t=$q->fetch();$ok('Empresa Auto Demo instalada',(bool)$t,$t?'tenant='.$t['id']:'não encontrada');
if($t){$id=(int)$t['id'];foreach(['customers'=>'Clientes','customer_vehicles'=>'Veículos','professionals'=>'Profissionais','auto_service_bays'=>'Boxes','services'=>'Serviços','auto_jobs'=>'Ordens Auto'] as $table=>$label){$s=$pdo->prepare("SELECT COUNT(*) FROM `$table` WHERE tenant_id=:t");$s->execute(['t'=>$id]);$n=(int)$s->fetchColumn();$ok($label,$n>0,(string)$n);} $ok('URL pública',(string)$t['public_slug']==='applanner-auto-demo',(string)$t['public_slug']);}
$ok('Landing comercial',is_file(dirname(__DIR__).'/app/Views/commercial/landing.php'));
$landing=@file_get_contents(dirname(__DIR__).'/app/Views/commercial/landing.php')?:'';$ok('CTA Auto Demo',str_contains($landing,'/auto/applanner-auto-demo'));
foreach($checks as [$n,$v,$d])echo ($v?'[OK] ':'[FALHA] ').$n.($d!==''?' — '.$d:'').PHP_EOL;
$failed=array_filter($checks,fn($c)=>!$c[1]);if($failed){fwrite(STDERR,'demo commercial smoke: FALHOU'.PHP_EOL);exit(1);}echo 'demo commercial smoke: OK ('.count($checks).' verificações)'.PHP_EOL;
