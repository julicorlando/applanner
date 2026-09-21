<?php
namespace App\Controllers;
use App\Core\{CSRF,RateLimiter};use App\Services\GrowthService;
final class GrowthController
{
 public function event():void{header('Content-Type: application/json; charset=utf-8');CSRF::enforce();$ip=(string)($_SERVER['REMOTE_ADDR']??'unknown');if(!RateLimiter::hit('growth|'.$ip,60,3600)){http_response_code(429);echo'{"ok":false}';return;}$raw=file_get_contents('php://input')?:'';$data=json_decode($raw,true);if(!is_array($data))$data=$_POST;$allowed=['ViewContent','Lead','CompleteRegistration','StartTrial'];$name=(string)($data['event_name']??'');if(!in_array($name,$allowed,true)){http_response_code(422);echo'{"ok":false}';return;}if(!empty($data['consent']))$_SESSION['marketing_consent']=true;$eventId=GrowthService::record($name,['segment'=>GrowthService::segment((string)($data['segment']??''))],null,null,(string)($data['event_id']??''),true);echo json_encode(['ok'=>true,'event_id'=>$eventId]);}
}
