<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Core\{Database,Encryption,CronLock};
use App\Services\PlatformSetting;

$pdo=Database::connection();$processed=0;
if(!CronLock::acquire('worker')){echo "Worker já está em execução.\n";exit(0);}
// Recupera jobs abandonados por queda abrupta sem duplicar jobs que já excederam tentativas.
$pdo->exec("UPDATE jobs SET status='failed',failed_at=COALESCE(failed_at,NOW()),locked_at=NULL,last_error=COALESCE(last_error,'Job abandonado excedeu o limite de tentativas.'),updated_at=NOW() WHERE status='processing' AND locked_at<DATE_SUB(NOW(),INTERVAL 15 MINUTE) AND attempts>=3");
$pdo->exec("UPDATE jobs SET status='queued',locked_at=NULL,available_at=NOW(),last_error=COALESCE(last_error,'Job recuperado após lock expirado.'),updated_at=NOW() WHERE status='processing' AND locked_at<DATE_SUB(NOW(),INTERVAL 15 MINUTE) AND attempts<3");
PlatformSetting::set('cron.last_run_at',date('Y-m-d H:i:s'),false);
while($processed<25){
    $pdo->beginTransaction();
    $job=$pdo->query("SELECT * FROM jobs WHERE status='queued' AND available_at<=NOW() AND (tenant_id IS NULL OR tenant_id IN (SELECT id FROM tenants WHERE COALESCE(is_demo,0)=0)) ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED")->fetch();
    if(!$job){$pdo->commit();break;}
    $pdo->prepare("UPDATE jobs SET status='processing',locked_at=NOW(),last_error=NULL,attempts=attempts+1,updated_at=NOW() WHERE id=:id")->execute(['id'=>$job['id']]);$pdo->commit();
    $payload=[];
    try{
        $payload=Encryption::decrypt($job['payload_encrypted']);
        $providerReference=null;
        if($job['type']==='marketing.lead_email'){
            sendLeadMarketing($pdo,$payload);
            $pdo->prepare("UPDATE marketing_deliveries SET status='sent',sent_at=NOW(),error_message=NULL,updated_at=NOW() WHERE id=:id")->execute(['id'=>(int)$payload['delivery_id']]);
            refreshMarketingCampaign($pdo,(int)$payload['campaign_id']);
        }elseif($job['type']==='campaign.send'){
            $reservedEmail=($payload['channel']??'')==='email'&&isReservedExampleEmail((string)($payload['destination']??''));
            if($reservedEmail){
                if(!empty($payload['recipient_id']))$pdo->prepare("UPDATE campaign_recipients SET status='skipped' WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['recipient_id'],'t'=>$job['tenant_id']]);
                if(!empty($payload['automation_log_id']))$pdo->prepare("UPDATE platform_automation_log SET status='skipped' WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['automation_log_id'],'t'=>$job['tenant_id']]);
                if(!empty($payload['notification_id']))$pdo->prepare("UPDATE notifications SET status='skipped',error_message='Destinatário fictício descartado automaticamente.' WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['notification_id'],'t'=>$job['tenant_id']]);
                if(!empty($payload['reminder_log_id']))$pdo->prepare("UPDATE appointment_reminder_log SET status='skipped',error_message='Destinatário fictício descartado automaticamente.' WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['reminder_log_id'],'t'=>$job['tenant_id']]);
                @file_put_contents(dirname(__DIR__).'/storage/logs/cron.log','['.date('c').'] job='.(int)$job['id']." skipped destinatário fictício\n",FILE_APPEND|LOCK_EX);
            }else{
                $providerReference=sendCampaign($pdo,$job,$payload);
            }
            if(!$reservedEmail&&!empty($payload['recipient_id']))$pdo->prepare("UPDATE campaign_recipients SET status='sent',sent_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['recipient_id'],'t'=>$job['tenant_id']]);
            if(!$reservedEmail&&!empty($payload['automation_log_id']))$pdo->prepare("UPDATE platform_automation_log SET status='sent' WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['automation_log_id'],'t'=>$job['tenant_id']]);
            if(!$reservedEmail&&!empty($payload['notification_id']))$pdo->prepare("UPDATE notifications SET status='sent',sent_at=NOW(),provider_reference=:ref,error_message=NULL WHERE id=:id AND tenant_id=:t")->execute(['ref'=>$providerReference,'id'=>$payload['notification_id'],'t'=>$job['tenant_id']]);
            if(!empty($payload['whatsapp_message_id']))$pdo->prepare("UPDATE whatsapp_messages SET status='sent',sent_at=NOW(),provider_message_id=:ref,error_message=NULL WHERE id=:id AND tenant_id=:t")->execute(['ref'=>$providerReference,'id'=>$payload['whatsapp_message_id'],'t'=>$job['tenant_id']]);
            if(!empty($payload['reminder_log_id']))$pdo->prepare("UPDATE appointment_reminder_log SET status='sent',sent_at=NOW(),error_message=NULL WHERE id=:id AND tenant_id=:t")->execute(['id'=>$payload['reminder_log_id'],'t'=>$job['tenant_id']]);
        }else{
            sendSystemMail($pdo,$job,$payload);
        }
        $pdo->prepare("UPDATE jobs SET status='completed',payload_encrypted='',locked_at=NULL,last_error=NULL,updated_at=NOW() WHERE id=:id")->execute(['id'=>$job['id']]);
    }catch(Throwable $e){
        $attempts=(int)$job['attempts']+1;$failed=$attempts>=3;$delay=max(5,min(60,$attempts*5));
        $pdo->prepare("UPDATE jobs SET status=:status,available_at=DATE_ADD(NOW(),INTERVAL :delay MINUTE),locked_at=NULL,failed_at=IF(:failed=1,NOW(),failed_at),last_error=:error,updated_at=NOW() WHERE id=:id")->execute(['status'=>$failed?'failed':'queued','delay'=>$delay,'failed'=>$failed?1:0,'error'=>mb_substr($e->getMessage(),0,500),'id'=>$job['id']]);
        if($failed&&!empty($payload['automation_log_id']))$pdo->prepare("UPDATE platform_automation_log SET status='failed' WHERE id=:id")->execute(['id'=>$payload['automation_log_id']]);
        if(!empty($payload['notification_id']))$pdo->prepare("UPDATE notifications SET status=:s,error_message=:e WHERE id=:id AND tenant_id=:t")->execute(['s'=>$failed?'failed':'queued','e'=>substr($e->getMessage(),0,500),'id'=>$payload['notification_id'],'t'=>$job['tenant_id']]);
        if(!empty($payload['whatsapp_message_id']))$pdo->prepare("UPDATE whatsapp_messages SET status=:s,error_message=:e WHERE id=:id AND tenant_id=:t")->execute(['s'=>$failed?'failed':'queued','e'=>substr($e->getMessage(),0,500),'id'=>$payload['whatsapp_message_id'],'t'=>$job['tenant_id']]);
        if(!empty($payload['reminder_log_id']))$pdo->prepare("UPDATE appointment_reminder_log SET status=:s,error_message=:e WHERE id=:id AND tenant_id=:t")->execute(['s'=>$failed?'failed':'queued','e'=>substr($e->getMessage(),0,500),'id'=>$payload['reminder_log_id'],'t'=>$job['tenant_id']]);
        if($job['type']==='marketing.lead_email'&&$failed&&!empty($payload['delivery_id'])){$pdo->prepare("UPDATE marketing_deliveries SET status='failed',error_message=:e,updated_at=NOW() WHERE id=:id")->execute(['e'=>substr($e->getMessage(),0,500),'id'=>(int)$payload['delivery_id']]);refreshMarketingCampaign($pdo,(int)$payload['campaign_id']);}
        @file_put_contents(dirname(__DIR__).'/storage/logs/cron.log','['.date('c').'] job='.(int)$job['id'].' failed '.substr($e->getMessage(),0,160)."\n",FILE_APPEND|LOCK_EX);
    }
    $processed++;
}
echo "Jobs processados: $processed\n";

function platformSecret(PDO $pdo,string $key):array{$v=PlatformSetting::secret($key);if(!$v)throw new RuntimeException('Integração global não configurada.');return $v;}
function isReservedExampleEmail(string $email):bool{
    if(!filter_var($email,FILTER_VALIDATE_EMAIL))return false;
    $domain=mb_strtolower((string)substr(strrchr($email,'@'),1));
    return $domain==='example.com'||str_ends_with($domain,'.example.com')||$domain==='example.com.br'||str_ends_with($domain,'.example.com.br');
}
function sendLeadMarketing(PDO $pdo,array $payload):void{
    if(!filter_var($payload['to']??'',FILTER_VALIDATE_EMAIL)||empty($payload['subject'])||empty($payload['unsubscribe_url']))throw new RuntimeException('Campanha de marketing inválida.');
    if(trim((string)($payload['message']??''))===''&&empty($payload['image_url']))throw new RuntimeException('Campanha sem mensagem ou card.');
    $smtp=platformSecret($pdo,'platform.lead_marketing_smtp');
    $render=(new App\Services\EmailMarketingTemplateService())->build($payload);
    (new App\Services\SmtpProvider())->sendHtml($smtp,$payload['to'],(string)$payload['subject'],$render['text'],$render['html']);
}
function refreshMarketingCampaign(PDO $pdo,int $campaignId):void{
    $q=$pdo->prepare("SELECT SUM(status='sent') sent,SUM(status='failed') failed,COUNT(*) total FROM marketing_deliveries WHERE campaign_id=:c");$q->execute(['c'=>$campaignId]);$s=$q->fetch();$done=(int)$s['sent']+(int)$s['failed']>=(int)$s['total'];$pdo->prepare("UPDATE marketing_campaigns SET sent_count=:sent,failed_count=:failed,status=IF(:done=1,'completed','sending'),completed_at=IF(:done2=1,NOW(),NULL) WHERE id=:id")->execute(['sent'=>(int)$s['sent'],'failed'=>(int)$s['failed'],'done'=>$done?1:0,'done2'=>$done?1:0,'id'=>$campaignId]);
}
function sendCampaign(PDO $pdo,array $job,array $payload):?string{
    $channel=$payload['channel']??'';$destination=$payload['destination']??'';$message=$payload['message']??'';
    if($channel==='email'&&filter_var($destination,FILTER_VALIDATE_EMAIL)){$smtp=platformSecret($pdo,'platform.marketing_email');(new App\Services\SmtpProvider())->send($smtp,$destination,(string)($payload['subject']??'Mensagem de '.($smtp['from_name']??'Agenda')),$message);return null;}
    if($channel==='whatsapp'&&preg_match('/^\d{10,15}$/',$destination)){
        $cfg=platformSecret($pdo,'platform.whatsapp');if(!preg_match('/^\d+$/',$cfg['phone_number_id']??''))throw new RuntimeException('WhatsApp global inválido.');$version=$cfg['api_version']??'v21.0';
        $ch=curl_init('https://graph.facebook.com/'.$version.'/'.$cfg['phone_number_id'].'/messages');curl_setopt_array($ch,[CURLOPT_POST=>true,CURLOPT_RETURNTRANSFER=>true,CURLOPT_TIMEOUT=>15,CURLOPT_HTTPHEADER=>['Authorization: Bearer '.$cfg['access_token'],'Content-Type: application/json'],CURLOPT_POSTFIELDS=>json_encode(['messaging_product'=>'whatsapp','to'=>$destination,'type'=>'text','text'=>['body'=>$message]],JSON_THROW_ON_ERROR)]);$raw=curl_exec($ch);$status=curl_getinfo($ch,CURLINFO_RESPONSE_CODE);$curlError=curl_error($ch);curl_close($ch);if($raw!==false&&$status>=200&&$status<300){$data=json_decode($raw,true);return is_array($data)&&!empty($data['messages'][0]['id'])?(string)$data['messages'][0]['id']:null;}throw new RuntimeException('WhatsApp recusou o envio'.($curlError?': '.$curlError:'.'));
    }
    throw new RuntimeException('Destino ou canal inválido.');
}
function sendSystemMail(PDO $pdo,array $job,array $payload):void{
    if($job['type']!=='mail.send'||!filter_var($payload['to']??'',FILTER_VALIDATE_EMAIL))throw new RuntimeException('Job inválido.');
    $app=require dirname(__DIR__).'/config/app.php';$verification=($payload['template']??'')==='email_verification';$subject=($verification?'Confirme seu e-mail':'Defina ou redefina sua senha').' — '.($app['name']??'Agenda SaaS');$body=($verification?"Confirme seu endereço de e-mail:\n\n":"Acesse o link seguro para definir sua senha:\n\n").($payload['url']??'');
    try{$smtp=platformSecret($pdo,'platform.marketing_email');(new App\Services\SmtpProvider())->send($smtp,$payload['to'],$subject,$body);return;}catch(Throwable){}
    $headers=['From: '.($app['system_email']??'no-reply@localhost'),'Content-Type: text/plain; charset=UTF-8'];if(!mail($payload['to'],$subject,$body,implode("\r\n",$headers)))throw new RuntimeException('Servidor recusou o envio.');
}
