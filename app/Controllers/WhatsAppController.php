<?php
namespace App\Controllers;

use App\Core\{Auth,Authorization,CSRF,Database,TenantContext,View,HttpException,Audit};
use App\Services\{PlatformSetting,WhatsAppChatbotService};

final class WhatsAppController
{
    public function master():void
    {
        Auth::requireRole('master');$cfg=PlatformSetting::secret('platform.whatsapp');foreach(['access_token','app_secret'] as $k)unset($cfg[$k]);$tenants=Database::connection()->query("SELECT id,name,public_short_code,public_slug FROM tenants WHERE status IN('trial','active') ORDER BY name LIMIT 500")->fetchAll();View::render('master/whatsapp-chatbot',['title'=>'Chatbot WhatsApp','config'=>$cfg,'tenants'=>$tenants]);
    }
    public function save():void
    {
        Auth::requireRole('master');CSRF::enforce();$old=PlatformSetting::secret('platform.whatsapp');$cfg=['phone_number_id'=>preg_replace('/\D/','',(string)($_POST['phone_number_id']??'')),'display_phone'=>preg_replace('/\D/','',(string)($_POST['display_phone']??'')),'api_version'=>trim((string)($_POST['api_version']??'v21.0')),'test_tenant_id'=>(int)($_POST['test_tenant_id']??0),'verify_token'=>trim((string)($_POST['verify_token']??'')),'access_token'=>(string)($_POST['access_token']??''),'app_secret'=>(string)($_POST['app_secret']??'')];foreach(['access_token','app_secret'] as $secret)if($cfg[$secret]==='')$cfg[$secret]=(string)($old[$secret]??'');if(!preg_match('/^\d+$/',$cfg['phone_number_id'])||!preg_match('/^v\d+\.\d+$/',$cfg['api_version'])||strlen($cfg['verify_token'])<16||strlen($cfg['access_token'])<20||strlen($cfg['app_secret'])<16)HttpException::abort(422,'Preencha IDs, tokens e segredo do aplicativo corretamente.');PlatformSetting::setSecret('platform.whatsapp',$cfg);Audit::log('MASTER_WHATSAPP_CHATBOT_CONFIGURED','settings');header('Location: /master/whatsapp-chatbot?saved=1');exit;
    }
    public function test():void
    {
        Auth::requireRole('master');CSRF::enforce();$phone=preg_replace('/\D/','',(string)($_POST['phone']??''));if(preg_match('/^\d{10,11}$/',$phone))$phone='55'.$phone;if(!preg_match('/^\d{12,15}$/',$phone))HttpException::abort(422,'Informe o telefone com DDD.');$cfg=PlatformSetting::secret('platform.whatsapp');$tenant=(int)($cfg['test_tenant_id']??0);if(!$tenant)HttpException::abort(422,'Escolha a empresa de teste.');$pdo=Database::connection();$q=$pdo->prepare('SELECT id FROM whatsapp_conversations WHERE tenant_id=:t AND wa_id=:wa LIMIT 1');$q->execute(['t'=>$tenant,'wa'=>$phone]);$conversation=(int)$q->fetchColumn();if(!$conversation){$pdo->prepare("INSERT INTO whatsapp_conversations(tenant_id,wa_id,status,bot_state,last_message_at,created_at,updated_at)VALUES(:t,:wa,'bot','welcome',NOW(),NOW(),NOW())")->execute(['t'=>$tenant,'wa'=>$phone]);$conversation=(int)$pdo->lastInsertId();}(new WhatsAppChatbotService())->queue($tenant,$conversation,$phone,'Oi! O atendimento de teste do ApPlanner está conectado 😊 Responda esta mensagem contando o que você gostaria de agendar.','bot');header('Location: /master/whatsapp-chatbot?test=queued');exit;
    }
    public function inbox():void
    {
        Authorization::require('dashboard.view');$t=TenantContext::id();$q=Database::connection()->prepare("SELECT wc.*,c.name customer_name,(SELECT body FROM whatsapp_messages wm WHERE wm.conversation_id=wc.id ORDER BY wm.id DESC LIMIT 1) last_body,(SELECT COUNT(*) FROM whatsapp_messages wm WHERE wm.conversation_id=wc.id AND wm.direction='in') incoming_count FROM whatsapp_conversations wc LEFT JOIN customers c ON c.id=wc.customer_id AND c.tenant_id=wc.tenant_id WHERE wc.tenant_id=:t ORDER BY wc.status='waiting_human' DESC,wc.last_message_at DESC LIMIT 200");$q->execute(['t'=>$t]);View::render('whatsapp/index',['title'=>'Conversas do WhatsApp','conversations'=>$q->fetchAll()]);
    }
    public function show(string $id):void
    {
        Authorization::require('dashboard.view');$t=TenantContext::id();$pdo=Database::connection();$q=$pdo->prepare('SELECT wc.*,c.name customer_name,c.phone customer_phone FROM whatsapp_conversations wc LEFT JOIN customers c ON c.id=wc.customer_id AND c.tenant_id=wc.tenant_id WHERE wc.id=:id AND wc.tenant_id=:t');$q->execute(['id'=>(int)$id,'t'=>$t]);$conversation=$q->fetch();if(!$conversation)HttpException::abort(404,'Conversa não encontrada.');$q=$pdo->prepare('SELECT wm.*,u.name user_name FROM whatsapp_messages wm LEFT JOIN users u ON u.id=wm.user_id WHERE wm.conversation_id=:c AND wm.tenant_id=:t ORDER BY wm.id LIMIT 500');$q->execute(['c'=>$conversation['id'],'t'=>$t]);View::render('whatsapp/show',['title'=>'Conversa WhatsApp','conversation'=>$conversation,'messages'=>$q->fetchAll()]);
    }
    public function reply(string $id):void
    {
        Authorization::require('dashboard.view');CSRF::enforce();$t=TenantContext::id();$message=trim((string)($_POST['message']??''));if(mb_strlen($message)<1||mb_strlen($message)>2000)HttpException::abort(422,'Mensagem inválida.');$pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM whatsapp_conversations WHERE id=:id AND tenant_id=:t');$q->execute(['id'=>(int)$id,'t'=>$t]);$c=$q->fetch();if(!$c)HttpException::abort(404,'Conversa não encontrada.');$pdo->prepare("UPDATE whatsapp_conversations SET status='human',assigned_to=:u,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['u'=>Auth::user()['id'],'id'=>$c['id'],'t'=>$t]);(new WhatsAppChatbotService())->queue($t,(int)$c['id'],(string)$c['wa_id'],$message,'user',(int)Auth::user()['id']);header('Location: /whatsapp/conversations/'.$c['id']);exit;
    }
    public function bot(string $id):void{Authorization::require('dashboard.view');CSRF::enforce();$t=TenantContext::id();Database::connection()->prepare("UPDATE whatsapp_conversations SET status='bot',assigned_to=NULL,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>(int)$id,'t'=>$t]);header('Location: /whatsapp/conversations/'.$id);exit;}
}
