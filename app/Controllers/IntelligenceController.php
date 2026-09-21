<?php
namespace App\Controllers;

use App\Core\{Authorization,TenantContext,View,CSRF,Database,HttpException,Encryption,Audit};
use App\Services\{BehaviorEngine,ModuleService,PlatformSetting};

final class IntelligenceController
{
    public function index():void
    {
        ModuleService::require('behavior');Authorization::require('dashboard.view');$t=TenantContext::id();$items=(new BehaviorEngine())->opportunities($t,30);$channels=$this->channels($t);$summary=['total'=>count($items),'overdue'=>0,'due_soon'=>0,'consented'=>0,'potential'=>0.0];foreach($items as $item){$kind=($item['opportunity_type']??'')==='overdue'?'overdue':'due_soon';$summary[$kind]++;if(!empty($item['consent_marketing']))$summary['consented']++;$summary['potential']+=(float)($item['service_price_snapshot']??0);}View::render('intelligence/index',['title'=>'Inteligência de retorno','items'=>$items,'summary'=>$summary,'channels'=>$channels]);
    }

    public function send(string $id):void
    {
        ModuleService::require('behavior');Authorization::require('dashboard.view');CSRF::enforce();$t=TenantContext::id();$customerId=(int)$id;$channel=(string)($_POST['channel']??'');$message=trim((string)($_POST['message']??''));
        if(!in_array($channel,['email','whatsapp'],true)||mb_strlen($message)<10||mb_strlen($message)>1500)HttpException::abort(422,'Revise o canal e a mensagem.');$channels=$this->channels($t);if(empty($channels[$channel]))HttpException::abort(422,'Este canal não está liberado ou configurado para o plano.');
        $pdo=Database::connection();$q=$pdo->prepare("SELECT c.*,t.name tenant_name,t.public_slug,t.public_short_code FROM customers c JOIN tenants t ON t.id=c.tenant_id WHERE c.id=:id AND c.tenant_id=:t AND c.status='active' LIMIT 1");$q->execute(['id'=>$customerId,'t'=>$t]);$customer=$q->fetch();if(!$customer)HttpException::abort(404,'Cliente não encontrado.');if(empty($customer['consent_marketing']))HttpException::abort(422,'O cliente não autorizou mensagens de marketing.');
        $destination=$channel==='email'?trim((string)$customer['email']):preg_replace('/\D/','',(string)$customer['phone']);if($channel==='email'&&!filter_var($destination,FILTER_VALIDATE_EMAIL))HttpException::abort(422,'O cliente não possui e-mail válido.');if($channel==='whatsapp'){if(preg_match('/^\d{10,11}$/',$destination))$destination='55'.$destination;if(!preg_match('/^\d{12,13}$/',$destination))HttpException::abort(422,'O cliente não possui WhatsApp válido com DDD.');}
        $app=require dirname(__DIR__,2).'/config/app.php';$slug=$customer['public_slug']?:$customer['public_short_code'];$link=rtrim((string)($app['url']??''),'/').'/a/'.$slug;$message=strtr($message,['{cliente}'=>(string)$customer['name'],'{empresa}'=>(string)$customer['tenant_name'],'{link}'=>$link]);$subject='Um convite da '.(string)$customer['tenant_name'];
        $duplicate=$pdo->prepare("SELECT 1 FROM platform_automation_log WHERE tenant_id=:t AND customer_id=:c AND event_type='MANUAL_RETURN' AND channel=:ch AND scheduled_for=CURDATE() AND status IN('queued','sent') LIMIT 1");$duplicate->execute(['t'=>$t,'c'=>$customerId,'ch'=>$channel]);if($duplicate->fetchColumn())HttpException::abort(409,'Já existe um disparo deste canal para o cliente hoje.');
        $pdo->beginTransaction();try{$pdo->prepare("INSERT INTO platform_automation_log(tenant_id,customer_id,event_type,channel,scheduled_for,status,created_at)VALUES(:t,:c,'MANUAL_RETURN',:ch,CURDATE(),'queued',NOW())")->execute(['t'=>$t,'c'=>$customerId,'ch'=>$channel]);$log=(int)$pdo->lastInsertId();$pdo->prepare("INSERT INTO notifications(tenant_id,customer_id,channel,template_key,destination,payload_json,status,scheduled_at,created_at)VALUES(:t,:c,:ch,'MANUAL_RETURN',:dest,:payload,'queued',NOW(),NOW())")->execute(['t'=>$t,'c'=>$customerId,'ch'=>$channel,'dest'=>$destination,'payload'=>json_encode(['subject'=>$subject,'link'=>$link,'manual'=>true,'created_by'=>'intelligence_dashboard'],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR)]);$notification=(int)$pdo->lastInsertId();$payload=Encryption::encrypt(['automation_log_id'=>$log,'notification_id'=>$notification,'channel'=>$channel,'destination'=>$destination,'subject'=>$subject,'message'=>$message]);$pdo->prepare("INSERT INTO jobs(tenant_id,type,payload_encrypted,status,attempts,available_at,created_at,updated_at)VALUES(:t,'campaign.send',:p,'queued',0,NOW(),NOW(),NOW())")->execute(['t'=>$t,'p'=>$payload]);$pdo->commit();Audit::log('INTELLIGENCE_MANUAL_MESSAGE_QUEUED','customers',$customerId,null,['channel'=>$channel,'automation_log_id'=>$log]);}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
        header('Location: /intelligence?sent=1&customer='.rawurlencode((string)$customer['name']).'&channel='.$channel);exit;
    }

    private function channels(int $tenantId):array
    {
        $email=(bool)PlatformSetting::secret('platform.marketing_email');$whatsapp=(bool)PlatformSetting::secret('platform.whatsapp');$q=Database::connection()->prepare("SELECT p.features_json FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.tenant_id=:t AND s.status IN('trial','active') ORDER BY s.id DESC LIMIT 1");$q->execute(['t'=>$tenantId]);$features=json_decode((string)($q->fetchColumn()?:'{}'),true)?:[];$manual=!array_key_exists('automation_manual',$features)||!empty($features['automation_manual']);return ['email'=>$manual&&$email&&(!array_key_exists('automation_email',$features)||!empty($features['automation_email'])),'whatsapp'=>$manual&&$whatsapp&&(!array_key_exists('automation_whatsapp',$features)||!empty($features['automation_whatsapp']))];
    }
}
