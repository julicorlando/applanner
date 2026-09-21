<?php
namespace App\Services;

use App\Core\{Database,Encryption};

final class WhatsAppChatbotService
{
    public function receive(array $message,array $contact,array $metadata):void
    {
        $cfg=PlatformSetting::secret('platform.whatsapp');if(!empty($cfg['phone_number_id'])&&!hash_equals((string)$cfg['phone_number_id'],(string)($metadata['phone_number_id']??'')))throw new \RuntimeException('Mensagem recebida para número não autorizado.');$pdo=Database::connection();$providerId=(string)($message['id']??'');$waId=$this->phone((string)($message['from']??''));if(!$providerId||!$waId)return;
        $dup=$pdo->prepare('SELECT 1 FROM whatsapp_messages WHERE provider_message_id=:id');$dup->execute(['id'=>$providerId]);if($dup->fetchColumn())return;
        $text=trim((string)($message['text']['body']??$message['button']['text']??$message['interactive']['button_reply']['title']??''));if($text==='')$text='[Mensagem '.(string)($message['type']??'não textual').']';
        $conversation=$this->conversation($waId,$text);if(!$conversation)return;$tenant=(int)$conversation['tenant_id'];$cid=(int)$conversation['id'];
        $pdo->prepare("INSERT INTO whatsapp_messages(conversation_id,tenant_id,provider_message_id,direction,sender_type,message_type,body,status,created_at)VALUES(:c,:t,:p,'in','customer',:type,:body,'received',NOW())")->execute(['c'=>$cid,'t'=>$tenant,'p'=>$providerId,'type'=>substr((string)($message['type']??'text'),0,30),'body'=>$text]);
        $pdo->prepare('UPDATE whatsapp_conversations SET contact_name=COALESCE(NULLIF(:name,\'\'),contact_name),last_message_at=NOW(),updated_at=NOW() WHERE id=:id')->execute(['name'=>(string)($contact['profile']['name']??''),'id'=>$cid]);
        if(in_array($conversation['status'],['human','waiting_human'],true)){NotificationService::tenantOwners($tenant,'whatsapp.incoming','Nova mensagem no WhatsApp',$text,'/whatsapp/conversations/'.$cid,'info');return;}
        $reply=$this->reply($conversation,$text);if($reply!=='')$this->queue($tenant,$cid,$waId,$reply,'bot');
    }

    public function queue(int $tenantId,int $conversationId,string $destination,string $message,string $sender='user',?int $userId=null):void
    {
        $pdo=Database::connection();$destination=$this->phone($destination);if(preg_match('/^\d{10,11}$/',$destination))$destination='55'.$destination;if(!preg_match('/^\d{12,15}$/',$destination))throw new \DomainException('Número do WhatsApp inválido.');
        $pdo->beginTransaction();try{$pdo->prepare("INSERT INTO whatsapp_messages(conversation_id,tenant_id,direction,sender_type,user_id,message_type,body,status,created_at)VALUES(:c,:t,'out',:sender,:u,'text',:body,'queued',NOW())")->execute(['c'=>$conversationId,'t'=>$tenantId,'sender'=>$sender==='bot'?'bot':'user','u'=>$userId,'body'=>$message]);$messageId=(int)$pdo->lastInsertId();$payload=Encryption::encrypt(['channel'=>'whatsapp','destination'=>$destination,'subject'=>'WhatsApp','message'=>$message,'whatsapp_message_id'=>$messageId]);$pdo->prepare("INSERT INTO jobs(tenant_id,type,payload_encrypted,status,attempts,available_at,created_at,updated_at)VALUES(:t,'campaign.send',:p,'queued',0,NOW(),NOW(),NOW())")->execute(['t'=>$tenantId,'p'=>$payload]);$pdo->prepare('UPDATE whatsapp_conversations SET last_message_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['id'=>$conversationId,'t'=>$tenantId]);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
    }

    private function conversation(string $waId,string $text):array|false
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT * FROM whatsapp_conversations WHERE wa_id=:wa AND status<>'closed' ORDER BY id DESC LIMIT 1");$q->execute(['wa'=>$waId]);if($row=$q->fetch())return $row;
        $tenant=null;$q=$pdo->prepare("SELECT id FROM tenants WHERE status IN('trial','active') AND public_enabled=1 AND (LOWER(public_short_code)=LOWER(:code) OR LOWER(public_slug)=LOWER(:slug)) LIMIT 1");foreach(preg_split('/\s+/',preg_replace('/[^\pL\pN_-]+/u',' ',$text)) as $token){if(mb_strlen($token)<3)continue;$q->execute(['code'=>$token,'slug'=>$token]);if($id=$q->fetchColumn()){$tenant=(int)$id;break;}}
        if(!$tenant){$cfg=PlatformSetting::secret('platform.whatsapp');$tenant=(int)($cfg['test_tenant_id']??0);}if(!$tenant)return false;
        $local=preg_replace('/^55/','',$waId);$normalized="REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,'+',''),' ',''),'-',''),'(',''),')','')";$c=$pdo->prepare("SELECT id,name FROM customers WHERE tenant_id=:t AND ($normalized=:phone OR $normalized=:local) ORDER BY id DESC LIMIT 1");$c->execute(['t'=>$tenant,'phone'=>$waId,'local'=>$local]);$customer=$c->fetch();
        $pdo->prepare("INSERT INTO whatsapp_conversations(tenant_id,customer_id,wa_id,status,bot_state,last_message_at,created_at,updated_at)VALUES(:t,:c,:wa,'bot','welcome',NOW(),NOW(),NOW())")->execute(['t'=>$tenant,'c'=>$customer['id']??null,'wa'=>$waId]);$id=(int)$pdo->lastInsertId();$q=$pdo->prepare('SELECT * FROM whatsapp_conversations WHERE id=:id');$q->execute(['id'=>$id]);return $q->fetch();
    }

    private function reply(array $conversation,string $text):string
    {
        $pdo=Database::connection();$tenant=(int)$conversation['tenant_id'];$cid=(int)$conversation['id'];$lower=mb_strtolower($text);
        if(preg_match('/\b(atendente|humano|pessoa|equipe|reclama)/u',$lower)){$pdo->prepare("UPDATE whatsapp_conversations SET status='waiting_human',bot_state='human',updated_at=NOW() WHERE id=:id")->execute(['id'=>$cid]);NotificationService::tenantOwners($tenant,'whatsapp.handoff','Cliente aguardando atendimento','Uma conversa do WhatsApp pediu atendimento humano.','/whatsapp/conversations/'.$cid,'warning');return 'Claro. Vou chamar alguém da equipe para continuar com você por aqui. Pode levar só um pouquinho 😊';}
        $t=$pdo->prepare('SELECT name,public_slug,public_short_code FROM tenants WHERE id=:t');$t->execute(['t'=>$tenant]);$company=$t->fetch();$name='';if(!empty($conversation['customer_id'])){$c=$pdo->prepare('SELECT name FROM customers WHERE id=:c AND tenant_id=:t');$c->execute(['c'=>$conversation['customer_id'],'t'=>$tenant]);$name=(string)$c->fetchColumn();}
        $first=$name?explode(' ',$name)[0]:'';$services=$pdo->prepare('SELECT id,name FROM services WHERE tenant_id=:t AND active=1 ORDER BY name');$services->execute(['t'=>$tenant]);$matched=[];foreach($services->fetchAll() as $service){$words=array_filter(preg_split('/\s+/',mb_strtolower($service['name'])),fn($x)=>mb_strlen($x)>3);foreach($words as $word)if(str_contains($lower,$word)){$matched[$service['id']]=$service['name'];break;}}
        $app=require dirname(__DIR__,2).'/config/app.php';$link=rtrim((string)$app['url'],'/').'/a/'.($company['public_slug']?:$company['public_short_code']);
        if($matched){$pdo->prepare("UPDATE whatsapp_conversations SET bot_state='services_selected',context_json=:ctx,updated_at=NOW() WHERE id=:id")->execute(['ctx'=>json_encode(['service_ids'=>array_map('intval',array_keys($matched)),'services'=>array_values($matched)],JSON_UNESCAPED_UNICODE),'id'=>$cid]);return 'Entendi'.($first?', '.$first:'').' 😊 Você quer '.implode(' e ',array_values($matched)).'. Vou considerar tudo junto para encontrar um espacinho que funcione bem. Tem preferência por algum profissional? Se preferir, pode dizer “quem estiver disponível”.';}
        if(!empty($conversation['customer_id'])){$last=$pdo->prepare("SELECT s.name service_name,p.name professional_name FROM appointments a JOIN services s ON s.id=a.service_id LEFT JOIN professionals p ON p.id=a.professional_id WHERE a.tenant_id=:t AND a.customer_id=:c AND a.status='completed' ORDER BY a.starts_at DESC LIMIT 1");$last->execute(['t'=>$tenant,'c'=>$conversation['customer_id']]);if($history=$last->fetch())return 'Oi, '.$first.'! Que bom falar com você de novo 😊 Vi que da última vez você fez '.$history['service_name'].($history['professional_name']?' com '.$history['professional_name']:'').'. Quer repetir ou está pensando em fazer algo diferente? Você pode me dizer mais de um serviço, do seu jeito.';}
        return 'Oi! Eu cuido dos agendamentos da '.$company['name'].' por aqui 😊 Me conta o que você gostaria de fazer. Pode escrever mais de um serviço. Se quiser consultar a agenda diretamente, use: '.$link;
    }

    private function phone(string $phone):string{return preg_replace('/\D/','',$phone);}
}
