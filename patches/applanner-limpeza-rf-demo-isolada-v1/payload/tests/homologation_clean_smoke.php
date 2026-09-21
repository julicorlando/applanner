<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();$fail=[];
$tenants=$pdo->query("SELECT id,name,slug,is_demo FROM tenants WHERE deleted_at IS NULL ORDER BY id")->fetchAll()?:[];
$real=array_values(array_filter($tenants,fn($t)=>(int)$t['is_demo']===0));
$demo=array_values(array_filter($tenants,fn($t)=>(int)$t['is_demo']===1));
if(count($real)!==1)$fail[]='esperado exatamente 1 tenant real';
else{
 $n=mb_strtolower((string)$real[0]['name']);
 if(!str_contains($n,'rf')||!str_contains($n,'films'))$fail[]='tenant real não parece ser RF Films';
}
if(count($demo)!==1)$fail[]='esperado exatamente 1 tenant demo';
$failed=(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='failed'")->fetchColumn();if($failed!==0)$fail[]=$failed.' jobs failed';
$demoBilling=(int)$pdo->query("SELECT COUNT(*) FROM payments p JOIN tenants t ON t.id=p.tenant_id WHERE t.is_demo=1")->fetchColumn()
 +(int)$pdo->query("SELECT COUNT(*) FROM tenant_payment_connections c JOIN tenants t ON t.id=c.tenant_id WHERE t.is_demo=1")->fetchColumn()
 +(int)$pdo->query("SELECT COUNT(*) FROM tenant_payment_transactions x JOIN tenants t ON t.id=x.tenant_id WHERE t.is_demo=1")->fetchColumn();
if($demoBilling!==0)$fail[]=$demoBilling.' registros billing na demo';
echo "Tenants reais: ".count($real)." | demos: ".count($demo)." | jobs failed: {$failed} | billing demo: {$demoBilling}\n";
if($fail){foreach($fail as $f)fwrite(STDERR,"[FALHA] {$f}\n");exit(1);}
echo "homologation clean smoke: OK\n";
