<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';

use App\Core\Database;
use App\Services\NotificationService;

$pdo=Database::connection();
$q=$pdo->query("SELECT s.id,s.tenant_id,s.status,s.trial_ends_at,t.name tenant_name
    FROM subscriptions s JOIN tenants t ON t.id=s.tenant_id
    WHERE s.status='trial' AND s.trial_ends_at IS NOT NULL AND t.status IN('trial','active')
      AND COALESCE(t.is_demo,0)=0
      AND s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=s.tenant_id)");
$count=0;
foreach($q->fetchAll() as $s){
    $days=(int)(new DateTimeImmutable('today'))->diff(new DateTimeImmutable(substr((string)$s['trial_ends_at'],0,10)))->format('%r%a');
    $key=null;$title=null;$message=null;$severity='info';
    if(in_array($days,[7,3,1],true)){$key='trial_'.$days.'d';$title='Seu teste termina em '.$days.' dia'.($days===1?'':'s');$message='O período de teste termina em '.$days.' dia'.($days===1?'':'s').'. Veja seu plano para continuar sem interrupções.';$severity=$days===1?'warning':'info';}
    elseif($days<=0){$key='trial_expired';$title='Período de teste encerrado';$message='Seu período de teste terminou. Escolha um plano para liberar novamente os módulos operacionais.';$severity='warning';}
    if($key===null)continue;
    try{$pdo->prepare('INSERT INTO subscription_notice_log(tenant_id,subscription_id,notice_key,created_at)VALUES(:t,:s,:k,NOW())')->execute(['t'=>$s['tenant_id'],'s'=>$s['id'],'k'=>$key]);}
    catch(PDOException $e){if($e->getCode()==='23000')continue;throw $e;}
    NotificationService::tenantOwners((int)$s['tenant_id'],'subscription.'.$key,$title,$message,'/billing',$severity);$count++;
}
echo "Avisos de assinatura gerados: $count\n";
