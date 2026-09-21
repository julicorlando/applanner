<?php
namespace App\Services;
final class MercadoPagoSandboxValidator
{
 public function validate(array $config,callable $providerFactory):array{$checks=['credentials'=>false,'environment'=>false,'https_webhook'=>false,'api_connectivity'=>false,'secrets'=>true];$token=(string)($config['access_token']??'');$checks['credentials']=strlen($token)>=16&&($config['credential_origin']??'')==='test_confirmed';$checks['environment']=($config['environment']??'')==='sandbox';$url=(string)($config['webhook_url']??'');$checks['https_webhook']=filter_var($url,FILTER_VALIDATE_URL)!==false&&str_starts_with($url,'https://');if(!$checks['credentials']||!$checks['environment'])return ['status'=>'not_validated','checks'=>$checks];try{$provider=$providerFactory($token);$me=$provider->testConnection();$checks['api_connectivity']=!empty($me['id']);}catch(\Throwable){$checks['api_connectivity']=false;}return ['status'=>count(array_filter($checks))===count($checks)?'validated':'partial','checks'=>$checks];}
}
