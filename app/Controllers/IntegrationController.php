<?php
namespace App\Controllers;

use App\Core\{Auth,CSRF,Database,Encryption,View,Audit,HttpException};
use App\Services\{PlatformSetting,PremiumAutomationService};

final class IntegrationController
{
    public function index():void
    {
        Auth::requireRole('master');header('Cache-Control: no-store, private');$pdo=Database::connection();$data=[];$updated=[];foreach(['platform.marketing_email','platform.whatsapp'] as $key){$row=PlatformSetting::getRow($key);$v=PlatformSetting::secret($key);foreach(['password','access_token'] as $secret)unset($v[$secret]);$data[$key]=$v;$updated[$key]=$row['updated_at']??null;}$row=PlatformSetting::getRow('platform.automation');$data['platform.automation']=PlatformSetting::json('platform.automation');$updated['platform.automation']=$row['updated_at']??null;
        View::render('master/integrations-premium',['title'=>'Integrações globais','email'=>$data['platform.marketing_email']??[],'whatsapp'=>$data['platform.whatsapp']??[],'automation'=>$data['platform.automation']??[],'updated'=>$updated]);
    }

    public function save():void
    {
        Auth::requireRole('master');CSRF::enforce();$kind=(string)($_POST['kind']??'');$pdo=Database::connection();
        if($kind==='email'){
            $cfg=['from_name'=>trim((string)($_POST['from_name']??'')),'from_email'=>mb_strtolower(trim((string)($_POST['from_email']??''))),'reply_to'=>mb_strtolower(trim((string)($_POST['reply_to']??''))),'host'=>trim((string)($_POST['host']??'')),'port'=>(int)($_POST['port']??587),'encryption'=>(string)($_POST['encryption']??'tls'),'username'=>trim((string)($_POST['username']??'')),'password'=>(string)($_POST['password']??'')];
            if(strlen($cfg['from_name'])<2||!filter_var($cfg['from_email'],FILTER_VALIDATE_EMAIL)||!preg_match('/^[a-z0-9.-]+$/i',$cfg['host'])||!in_array($cfg['encryption'],['tls','ssl','none'],true))HttpException::abort(422,'Configuração de e-mail inválida.');
            if($cfg['password']===''){$old=$this->secret('platform.marketing_email');$cfg['password']=$old['password']??'';}if($cfg['password']==='')HttpException::abort(422,'Informe a senha SMTP.');$this->saveSecret('platform.marketing_email',$cfg);Audit::log('MASTER_EMAIL_INTEGRATION_UPDATED','settings');
        }elseif($kind==='whatsapp'){
            $old=$this->secret('platform.whatsapp');$cfg=$old+['phone_number_id'=>'','access_token'=>'','api_version'=>'v21.0'];$cfg['phone_number_id']=trim((string)($_POST['phone_number_id']??''));$cfg['api_version']=trim((string)($_POST['api_version']??'v21.0'));if((string)($_POST['access_token']??'')!=='')$cfg['access_token']=(string)$_POST['access_token'];
            if(!preg_match('/^\d+$/',$cfg['phone_number_id'])||!preg_match('/^v\d+\.\d+$/',$cfg['api_version']))HttpException::abort(422,'Configuração do WhatsApp inválida.');if($cfg['access_token']==='')HttpException::abort(422,'Informe o Access Token.');$this->saveSecret('platform.whatsapp',$cfg);Audit::log('MASTER_WHATSAPP_INTEGRATION_UPDATED','settings');
        }elseif($kind==='automation'){
            $cfg=['enabled'=>isset($_POST['enabled']),'email_enabled'=>isset($_POST['email_enabled']),'whatsapp_enabled'=>isset($_POST['whatsapp_enabled']),'days_before'=>max(0,min(15,(int)($_POST['days_before']??2))),'cooldown_days'=>max(1,min(60,(int)($_POST['cooldown_days']??14))),'daily_limit'=>max(1,min(10000,(int)($_POST['daily_limit']??500))),'start_hour'=>max(0,min(23,(int)($_POST['start_hour']??8))),'end_hour'=>max(1,min(24,(int)($_POST['end_hour']??20))),'pause_until'=>preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/',(string)($_POST['pause_until']??''))?str_replace('T',' ',(string)$_POST['pause_until']).':00':null,'subject'=>trim((string)($_POST['subject']??'Está chegando a hora de voltar')),'message'=>trim((string)($_POST['message']??'Olá {cliente}, sentimos sua falta na {empresa}. Próximos horários: {disponibilidade}. Agende: {link}')),'birthday_subject'=>trim((string)($_POST['birthday_subject']??'Um presente especial no seu aniversário 🎉')),'birthday_message'=>trim((string)($_POST['birthday_message']??'Parabéns, {cliente}! A equipe {empresa} deseja um dia incrível. Horários para você: {disponibilidade}. Agende: {link}'))];if(strlen($cfg['message'])<10||strlen($cfg['birthday_message'])<10)HttpException::abort(422,'As mensagens automáticas estão muito curtas.');$value=json_encode($cfg,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);PlatformSetting::set('platform.automation',$value,false);Audit::log('MASTER_AUTOMATION_UPDATED','settings',null,null,['enabled'=>$cfg['enabled'],'email'=>$cfg['email_enabled'],'whatsapp'=>$cfg['whatsapp_enabled']]);
        }elseif($kind==='automation_templates'){
            $cfg=PlatformSetting::json('platform.automation');$cfg['subject']=trim((string)($_POST['subject']??''));$cfg['message']=trim((string)($_POST['message']??''));$cfg['birthday_subject']=trim((string)($_POST['birthday_subject']??''));$cfg['birthday_message']=trim((string)($_POST['birthday_message']??''));if(strlen($cfg['message'])<10||strlen($cfg['birthday_message'])<10)HttpException::abort(422,'As mensagens precisam ter pelo menos 10 caracteres.');PlatformSetting::set('platform.automation',json_encode($cfg,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR),false);Audit::log('MASTER_AUTOMATION_TEMPLATES_UPDATED','settings');
        }else HttpException::abort(422,'Integração inválida.');
        header('Location: /master/integrations');exit;
    }

    public function dispatchAutomation():void
    {
        Auth::requireRole('master');CSRF::enforce();$tenant=filter_var($_POST['tenant_id']??null,FILTER_VALIDATE_INT);$result=(new PremiumAutomationService())->dispatch(true,$tenant?:(null));Audit::log('MASTER_AUTOMATION_MANUAL_DISPATCH','jobs',null,null,$result+['tenant_id'=>$tenant?:null]);header('Location: /master/integrations?queued='.(int)$result['queued'].'&customers='.(int)$result['customers']);exit;
    }

    private function saveSecret(string $key,array $cfg):void{PlatformSetting::setSecret($key,$cfg);}
    private function secret(string $key):array{return PlatformSetting::secret($key);}
}
