<?php
namespace App\Controllers;

use App\Core\{Auth,CSRF,Database,Encryption,View,Audit,HttpException};
use App\Services\{MercadoPagoProvider,MercadoPagoSandboxValidator,PlatformSetting};

final class MercadoPagoController
{
    public function index():void
    {
        Auth::requireRole('master');header('Cache-Control: no-store, private');$pdo=Database::connection();
        $rows=[];foreach(['sandbox','production'] as $env)$rows[$env]=$this->row($env);
        $result=$_SESSION['mp_validation']??null;unset($_SESSION['mp_validation']);
        $app=require __DIR__.'/../../config/app.php';$defaultWebhook=rtrim($app['url'],'/').'/webhooks/mercadopago';
        View::render('master/mercadopago',['title'=>'Mercado Pago','gateways'=>$rows,'configured'=>['sandbox'=>!empty($rows['sandbox']['access_token_encrypted']),'production'=>!empty($rows['production']['access_token_encrypted'])],'result'=>$result,'defaultWebhook'=>$defaultWebhook,'sandboxValidatedAt'=>PlatformSetting::get('mercadopago.sandbox_validated_at'),'activeEnvironment'=>PlatformSetting::get('mercadopago.active_environment','sandbox')]);
    }

    public function save():void
    {
        Auth::requireRole('master');CSRF::enforce();$this->reauth((string)($_POST['password']??''));$env=(string)($_POST['environment']??'sandbox');if(!in_array($env,['sandbox','production'],true))HttpException::abort(422,'Ambiente inválido.');
        if($env==='sandbox'&&!isset($_POST['confirm_test_credential']))HttpException::abort(422,'Confirme que a credencial veio da área de testes.');
        if($env==='production'){if(!isset($_POST['confirm_production']))HttpException::abort(422,'Confirme que entende que o ambiente de produção realiza cobranças reais.');if(!PlatformSetting::get('mercadopago.sandbox_validated_at'))HttpException::abort(422,'Homologue primeiro o ambiente de teste antes de cadastrar produção.');}
        $existing=$this->row($env);$token=trim((string)($_POST['access_token']??''));$public=trim((string)($_POST['public_key']??''));$secret=trim((string)($_POST['webhook_secret']??''));$url=trim((string)($_POST['webhook_url']??''));
        if($token===''&&$existing)$token='__KEEP__';if($secret===''&&$existing)$secret='__KEEP__';if(($token===''||$secret==='')||!str_starts_with($url,'https://'))HttpException::abort(422,'Informe as credenciais e uma URL HTTPS para o webhook.');
        $tokenEncrypted=$token==='__KEEP__'?$existing['access_token_encrypted']:Encryption::encrypt(['value'=>$token]);$secretEncrypted=$secret==='__KEEP__'?$existing['webhook_secret_encrypted']:Encryption::encrypt(['value'=>$secret]);
        $pdo=Database::connection();$q=$pdo->prepare("INSERT INTO payment_gateways(provider,environment,public_key,access_token_encrypted,webhook_secret_encrypted,active,last_test_status,updated_at)VALUES('mercadopago',:env,:public,:token,:secret,0,'not_validated',NOW()) ON DUPLICATE KEY UPDATE public_key=VALUES(public_key),access_token_encrypted=VALUES(access_token_encrypted),webhook_secret_encrypted=VALUES(webhook_secret_encrypted),active=0,last_test_status='not_validated',updated_at=NOW()");$q->execute(['env'=>$env,'public'=>$public?:($existing['public_key']??null),'token'=>$tokenEncrypted,'secret'=>$secretEncrypted]);
        PlatformSetting::set('mercadopago.webhook_url.'.$env,$url,false);if($env==='sandbox')PlatformSetting::set('mercadopago.credential_origin.sandbox','test_confirmed',false);
        Audit::log('MERCADOPAGO_GATEWAY_CONFIGURED','payment_gateways',null,null,['environment'=>$env]);$_SESSION['mp_validation']=['environment'=>$env,'status'=>'saved','message'=>'Configurações salvas. Execute a validação antes de ativar este ambiente.'];header('Location: /master/mercadopago');exit;
    }

    public function validateSandbox():void
    {
        Auth::requireRole('master');CSRF::enforce();$row=$this->row('sandbox');if(!$row||!$row['access_token_encrypted'])HttpException::abort(422,'Credenciais do ambiente de teste não configuradas.');$token=Encryption::decrypt($row['access_token_encrypted'])['value']??'';$result=(new MercadoPagoSandboxValidator())->validate(['access_token'=>$token,'credential_origin'=>PlatformSetting::get('mercadopago.credential_origin.sandbox',PlatformSetting::get('mercadopago.credential_origin','')),'environment'=>'sandbox','webhook_url'=>PlatformSetting::get('mercadopago.webhook_url.sandbox',PlatformSetting::get('mercadopago.webhook_url',''))],fn($t)=>new MercadoPagoProvider($t));$pdo=Database::connection();$pdo->prepare("UPDATE payment_gateways SET last_tested_at=NOW(),last_test_status=:s,active=IF(:s2='validated',1,0),updated_at=NOW() WHERE provider='mercadopago' AND environment='sandbox'")->execute(['s'=>$result['status'],'s2'=>$result['status']]);if($result['status']==='validated'){PlatformSetting::set('mercadopago.sandbox_validated_at',date('Y-m-d H:i:s'),false);if(!PlatformSetting::get('mercadopago.active_environment'))PlatformSetting::set('mercadopago.active_environment','sandbox',false);}$_SESSION['mp_validation']=$result+['environment'=>'sandbox'];Audit::log('MERCADOPAGO_SANDBOX_VALIDATION','payment_gateways',null,null,['status'=>$result['status']]);header('Location: /master/mercadopago');exit;
    }

    public function testConnection():void
    {
        Auth::requireRole('master');CSRF::enforce();$this->reauth((string)($_POST['password']??''));$env=(string)($_POST['environment']??'sandbox');if(!in_array($env,['sandbox','production'],true))HttpException::abort(422,'Ambiente inválido.');$row=$this->row($env);if(!$row||!$row['access_token_encrypted'])HttpException::abort(422,'Credenciais não configuradas.');if($env==='production'&&!PlatformSetting::get('mercadopago.sandbox_validated_at'))HttpException::abort(422,'O ambiente de teste precisa estar homologado antes da produção.');
        try{$token=Encryption::decrypt($row['access_token_encrypted'])['value']??'';$me=(new MercadoPagoProvider($token))->testConnection();if(empty($me['id']))throw new \RuntimeException('Resposta inesperada.');Database::connection()->beginTransaction();Database::connection()->prepare("UPDATE payment_gateways SET last_tested_at=NOW(),last_test_status='validated',active=1,updated_at=NOW() WHERE provider='mercadopago' AND environment=:env")->execute(['env'=>$env]);if($env==='production')Database::connection()->prepare("UPDATE payment_gateways SET active=0 WHERE provider='mercadopago' AND environment='sandbox'")->execute();Database::connection()->commit();PlatformSetting::set('mercadopago.active_environment',$env,false);$_SESSION['mp_validation']=['environment'=>$env,'status'=>'validated','message'=>'Conexão autenticada com sucesso.','checks'=>['Autenticação com a API'=>true,'Credencial protegida'=>true,'Webhook HTTPS'=>str_starts_with((string)PlatformSetting::get('mercadopago.webhook_url.'.$env,PlatformSetting::get('mercadopago.webhook_url','')),'https://')]];Audit::log('MERCADOPAGO_CONNECTION_VALIDATED','payment_gateways',null,null,['environment'=>$env]);}catch(\Throwable $e){if(Database::connection()->inTransaction())Database::connection()->rollBack();Database::connection()->prepare("UPDATE payment_gateways SET last_tested_at=NOW(),last_test_status='failed',active=0,updated_at=NOW() WHERE provider='mercadopago' AND environment=:env")->execute(['env'=>$env]);$_SESSION['mp_validation']=['environment'=>$env,'status'=>'failed','message'=>'Não foi possível autenticar. Confira as credenciais e o ambiente.'];}
        header('Location: /master/mercadopago');exit;
    }

    private function row(string $environment):array|false{$q=Database::connection()->prepare("SELECT id,provider,environment,public_key,access_token_encrypted,webhook_secret_encrypted,active,last_tested_at,last_test_status,updated_at FROM payment_gateways WHERE provider='mercadopago' AND environment=:env LIMIT 1");$q->execute(['env'=>$environment]);return $q->fetch();}
    public function savePixSettings():void{Auth::requireRole('master');CSRF::enforce();$hours=filter_var($_POST['expiration_hours']??null,FILTER_VALIDATE_INT,['options'=>['min_range'=>1,'max_range'=>720]]);$discount=filter_var(str_replace(',','.',(string)($_POST['discount_percent']??'0')),FILTER_VALIDATE_FLOAT);if($hours===false||$discount===false||$discount<0||$discount>50)HttpException::abort(422,'Configuração Pix inválida.');PlatformSetting::set('mercadopago.pix.enabled',isset($_POST['enabled'])?'1':'0',false);PlatformSetting::set('mercadopago.pix.expiration_hours',(string)$hours,false);PlatformSetting::set('mercadopago.pix.discount_percent',number_format((float)$discount,2,'.',''),false);Audit::log('MERCADOPAGO_PIX_SETTINGS','settings',null,null,['enabled'=>isset($_POST['enabled']),'expiration_hours'=>$hours,'discount_percent'=>$discount]);header('Location: /master/mercadopago?pix_saved=1');exit;}
    private function reauth(string $password):void{$q=Database::connection()->prepare('SELECT password_hash,two_factor_enabled_at FROM users WHERE id=:id');$q->execute(['id'=>Auth::user()['id']]);$u=$q->fetch();if(!$u||!$u['two_factor_enabled_at']||!password_verify($password,$u['password_hash']))HttpException::abort(403,'Reautenticação com senha e autenticação em dois fatores ativa são obrigatórias.');}
}
