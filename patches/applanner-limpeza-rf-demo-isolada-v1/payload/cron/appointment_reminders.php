<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';

use App\Core\{Database,Encryption};
use App\Services\PlatformSetting;

$pdo=Database::connection();$app=require dirname(__DIR__).'/config/app.php';
$emailConfigured=(bool)PlatformSetting::secret('platform.marketing_email');$waConfigured=(bool)PlatformSetting::secret('platform.whatsapp');
$rows=$pdo->query("SELECT a.id,a.tenant_id,a.starts_at,a.customer_manage_token_encrypted,c.id customer_id,c.name customer_name,c.email,c.phone,t.name tenant_name,s.name service_name,p.name professional_name,ss.reminder_24h_enabled,ss.reminder_2h_enabled
FROM appointments a JOIN customers c ON c.id=a.customer_id AND c.tenant_id=a.tenant_id JOIN tenants t ON t.id=a.tenant_id JOIN services s ON s.id=a.service_id JOIN professionals p ON p.id=a.professional_id LEFT JOIN tenant_schedule_settings ss ON ss.tenant_id=a.tenant_id
WHERE t.status IN('trial','active') AND COALESCE(t.is_demo,0)=0 AND a.status IN('pending','confirmed') AND a.starts_at BETWEEN NOW() AND DATE_ADD(NOW(),INTERVAL 26 HOUR)
ORDER BY a.starts_at LIMIT 1000")->fetchAll();
$queued=0;$now=new DateTimeImmutable();
foreach($rows as $r){
    $start=new DateTimeImmutable($r['starts_at']);$minutes=(int)round(($start->getTimestamp()-$now->getTimestamp())/60);
    $keys=[];
    if(($r['reminder_24h_enabled']??1)&&$minutes>=1380&&$minutes<=1560)$keys[]='24h';
    if(($r['reminder_2h_enabled']??0)&&$minutes>=90&&$minutes<=150)$keys[]='2h';
    foreach($keys as $key){
        $manage='';if(!empty($r['customer_manage_token_encrypted'])){try{$d=Encryption::decrypt($r['customer_manage_token_encrypted']);$manage=!empty($d['token'])?rtrim($app['url']??'','/').'/booking/'.$d['token']:'';}catch(Throwable){}}
        $subject='Lembrete do seu agendamento';$message="Olá {$r['customer_name']}, lembramos seu agendamento em {$r['tenant_name']} para {$start->format('d/m/Y H:i')}, serviço {$r['service_name']} com {$r['professional_name']}.".($manage?" Gerencie aqui: {$manage}":'');
        $channels=[];if($emailConfigured&&filter_var($r['email']??'',FILTER_VALIDATE_EMAIL))$channels['email']=$r['email'];$phone=preg_replace('/\D/','',(string)($r['phone']??''));if($waConfigured&&preg_match('/^\d{10,15}$/',$phone))$channels['whatsapp']=$phone;
        foreach($channels as $channel=>$dest){
            try{$pdo->beginTransaction();$pdo->prepare("INSERT INTO appointment_reminder_log(tenant_id,appointment_id,reminder_key,channel,status,created_at)VALUES(:t,:a,:k,:ch,'queued',NOW())")->execute(['t'=>$r['tenant_id'],'a'=>$r['id'],'k'=>$key,'ch'=>$channel]);$rid=(int)$pdo->lastInsertId();$pdo->prepare("INSERT INTO notifications(tenant_id,customer_id,channel,template_key,destination,payload_json,status,scheduled_at,created_at)VALUES(:t,:c,:ch,:tpl,:dest,:payload,'queued',NOW(),NOW())")->execute(['t'=>$r['tenant_id'],'c'=>$r['customer_id'],'ch'=>$channel,'tpl'=>'APPOINTMENT_REMINDER_'.strtoupper($key),'dest'=>$dest,'payload'=>json_encode(['appointment_id'=>$r['id'],'starts_at'=>$r['starts_at'],'manage_url'=>$manage],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR)]);$nid=(int)$pdo->lastInsertId();$payload=Encryption::encrypt(['reminder_log_id'=>$rid,'notification_id'=>$nid,'channel'=>$channel,'destination'=>$dest,'subject'=>$subject,'message'=>$message]);$pdo->prepare("INSERT INTO jobs(tenant_id,type,payload_encrypted,status,attempts,available_at,created_at,updated_at)VALUES(:t,'campaign.send',:p,'queued',0,NOW(),NOW(),NOW())")->execute(['t'=>$r['tenant_id'],'p'=>$payload]);$pdo->commit();$queued++;}catch(PDOException $e){if($pdo->inTransaction())$pdo->rollBack();if(($e->errorInfo[1]??0)!==1062)throw $e;}
        }
    }
}
echo "Lembretes enfileirados: {$queued}\n";
