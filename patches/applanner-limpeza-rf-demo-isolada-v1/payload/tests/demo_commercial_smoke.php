<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();$checks=[];$ok=function($n,$v,$d='')use(&$checks){$checks[]=[$n,(bool)$v,$d];echo ($v?'[OK] ':'[FALHA] ').$n.($d!==''?' — '.$d:'').PHP_EOL;};
$q=$pdo->prepare("SELECT id,public_slug,category,is_demo FROM tenants WHERE slug='auto-prime-demonstracao' LIMIT 1");$q->execute();$t=$q->fetch();
$ok('Empresa Auto Demo instalada',(bool)$t,$t?'tenant='.$t['id']:'não encontrada');
if($t){
  $id=(int)$t['id'];$ok('Demo marcada is_demo',(int)$t['is_demo']===1,'is_demo='.$t['is_demo']);
  foreach(['customers'=>'Clientes','customer_vehicles'=>'Veículos','professionals'=>'Profissionais','auto_service_bays'=>'Boxes','services'=>'Serviços','auto_jobs'=>'Ordens Auto'] as $table=>$label){$s=$pdo->prepare("SELECT COUNT(*) FROM `$table` WHERE tenant_id=:t");$s->execute(['t'=>$id]);$n=(int)$s->fetchColumn();$ok($label,$n>0,(string)$n);}
  $ok('URL pública',(string)$t['public_slug']==='applanner-auto-demo',(string)$t['public_slug']);
  $s=$pdo->prepare("SELECT COUNT(*) FROM payments WHERE tenant_id=:t");$s->execute(['t'=>$id]);$ok('Sem payments reais',(int)$s->fetchColumn()===0);
  $s=$pdo->prepare("SELECT COUNT(*) FROM tenant_payment_connections WHERE tenant_id=:t");$s->execute(['t'=>$id]);$ok('Sem conexão de pagamento real',(int)$s->fetchColumn()===0);
  $s=$pdo->prepare("SELECT COUNT(*) FROM subscription_exemptions WHERE tenant_id=:t AND status='active' AND exemption_type='permanent'");$s->execute(['t'=>$id]);$ok('Isenção permanente da demo',(int)$s->fetchColumn()===1);
}
$failed=array_filter($checks,fn($c)=>!$c[1]);if($failed){fwrite(STDERR,'demo isolated smoke: FALHOU'.PHP_EOL);exit(1);}echo 'demo isolated smoke: OK ('.count($checks).' verificações)'.PHP_EOL;
