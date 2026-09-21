<?php
namespace App\Services;
use App\Core\Database;
final class MetaConversionService
{
 public function send(array $event):void
 {
  $config=PlatformSetting::secret('growth.meta_capi');$pixel=preg_replace('/\D/','',(string)($config['pixel_id']??''));$token=(string)($config['access_token']??'');if($pixel===''||$token==='')throw new \RuntimeException('Meta Conversion API não configurada.');$version=preg_match('/^v\d{1,2}\.\d$/',(string)($config['api_version']??''))?(string)$config['api_version']:'v21.0';
  $user=[];if(!empty($event['email']))$user['em']=[hash('sha256',mb_strtolower(trim((string)$event['email'])))];if(!empty($event['phone']))$user['ph']=[hash('sha256',preg_replace('/\D/','',(string)$event['phone']))];if(!empty($event['client_ip_address']))$user['client_ip_address']=$event['client_ip_address'];if(!empty($event['client_user_agent']))$user['client_user_agent']=$event['client_user_agent'];
  $item=['event_name'=>$event['event_name'],'event_time'=>(int)$event['event_time'],'event_id'=>$event['event_id'],'action_source'=>'website','event_source_url'=>$event['event_source_url']??null,'user_data'=>$user];if(isset($event['value']))$item['custom_data']=['value'=>round((float)$event['value'],2),'currency'=>$event['currency']??'BRL'];$body=['data'=>[$item]];if(!empty($config['test_event_code']))$body['test_event_code']=$config['test_event_code'];
  $ch=curl_init('https://graph.facebook.com/'.$version.'/'.$pixel.'/events?access_token='.rawurlencode($token));curl_setopt_array($ch,[CURLOPT_POST=>true,CURLOPT_RETURNTRANSFER=>true,CURLOPT_TIMEOUT=>15,CURLOPT_HTTPHEADER=>['Content-Type: application/json'],CURLOPT_POSTFIELDS=>json_encode($body,JSON_THROW_ON_ERROR)]);$raw=curl_exec($ch);$status=(int)curl_getinfo($ch,CURLINFO_RESPONSE_CODE);$err=curl_error($ch);curl_close($ch);$ok=$raw!==false&&$status>=200&&$status<300;
  $pdo=Database::connection();$pdo->prepare("UPDATE meta_conversion_log SET status=:s,http_status=:h,response_excerpt=:r,attempts=attempts+1,sent_at=IF(:ok=1,NOW(),sent_at),updated_at=NOW() WHERE event_id=:id")->execute(['s'=>$ok?'sent':'failed','h'=>$status?:null,'r'=>mb_substr($raw!==false?$raw:$err,0,500),'ok'=>$ok?1:0,'id'=>$event['event_id']]);if(!$ok)throw new \RuntimeException('Meta CAPI recusou o evento (HTTP '.$status.'): '.mb_substr($raw!==false?$raw:$err,0,180));
 }
}
