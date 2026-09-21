<?php
namespace App\Controllers;

use App\Core\{Database,Encryption,RateLimiter,SecurityLogger};
use App\Services\MercadoPagoProvider;
use App\Services\BarberMembershipPaymentService;

final class TenantPaymentWebhookController
{
    public function mercadoPago(string $tenant): void
    {
        $ip=(string)($_SERVER['REMOTE_ADDR']??'unknown');
        if(!RateLimiter::hit('tenant-mp-webhook|'.$ip,180,60)){http_response_code(429);return;}
        $raw=file_get_contents('php://input')?:'';$payload=json_decode($raw,true);
        if(!is_array($payload)){http_response_code(400);return;}
        $dataId=(string)($payload['data']['id']??$_GET['data_id']??'');
        $signature=(string)($_SERVER['HTTP_X_SIGNATURE']??'');$requestId=(string)($_SERVER['HTTP_X_REQUEST_ID']??'');
        if($dataId===''||$signature===''||$requestId===''){http_response_code(401);return;}

        $pdo=Database::connection();$q=$pdo->prepare("SELECT pc.*,t.id tenant_id,t.public_slug,t.public_short_code FROM tenants t JOIN tenant_payment_connections pc ON pc.tenant_id=t.id WHERE (t.public_slug=:slug OR t.public_short_code=:code) AND pc.provider='mercadopago' AND pc.status='connected' ORDER BY (pc.environment='production') DESC,pc.id DESC LIMIT 1");
        $q->execute(['slug'=>$tenant,'code'=>$tenant]);$connection=$q->fetch();if(!$connection){http_response_code(404);return;}
        try{$credentials=Encryption::decrypt((string)$connection['credentials_encrypted']);}catch(\Throwable){http_response_code(503);return;}
        $secret=(string)($credentials['webhook_secret']??'');
        if(!MercadoPagoProvider::validWebhookSignature($signature,$requestId,$dataId,$secret)){
            SecurityLogger::log('payments.webhook.invalid_signature',['tenant_id'=>(int)$connection['tenant_id'],'provider'=>'mercadopago']);http_response_code(401);return;
        }
        $eventType=(string)($payload['type']??$payload['action']??'event');
        $eventId=substr(hash('sha256',$requestId.'|'.$dataId.'|'.$eventType),0,64);
        try{$pdo->prepare("INSERT INTO tenant_payment_webhook_events(connection_id,tenant_id,provider,event_id,payload_hash,signature_valid,status,received_at) VALUES(:connection,:tenant,'mercadopago',:event,:hash,1,'received',NOW())")->execute(['connection'=>$connection['id'],'tenant'=>$connection['tenant_id'],'event'=>$eventId,'hash'=>hash('sha256',$raw)]);}catch(\PDOException $e){if($e->getCode()==='23000'){http_response_code(204);return;}throw $e;}

        try{
            $provider=new MercadoPagoProvider((string)($credentials['access_token']??''));
            $remote=$this->fetchRemote($provider,$dataId,$eventType);$external=(string)($remote['external_reference']??'');$remoteId=(string)($remote['id']??$dataId);$remoteStatus=$this->remoteStatus($remote,$eventType);$amount=$this->remoteAmount($remote);
            $pdo->beginTransaction();
            if($this->isSubscriptionPreapprovalEvent($eventType,$remote)){
                $this->processSubscription($pdo,(int)$connection['tenant_id'],(int)$connection['id'],$remoteId,$external,$remoteStatus);
            } elseif($this->isAuthorizedSubscriptionPaymentEvent($eventType)) {
                if(!$this->isBarberMembershipPayment($external))throw new \DomainException('authorized_subscription_not_supported');
                $this->processMembershipPayment($pdo,(int)$connection['tenant_id'],(int)$connection['id'],'authorized-'.$remoteId,$external,$remoteStatus,$amount,$remote);
            } elseif($this->isBarberMembershipPayment($external)) {
                $this->processMembershipPayment($pdo,(int)$connection['tenant_id'],(int)$connection['id'],$remoteId,$external,$remoteStatus,$amount,$remote);
            } else {
                $this->processTransaction($pdo,(int)$connection['tenant_id'],(int)$connection['id'],$remoteId,$external,$remoteStatus,$amount);
            }
            $pdo->prepare("UPDATE tenant_payment_webhook_events SET status='processed',processed_at=NOW() WHERE connection_id=:c AND event_id=:e")->execute(['c'=>$connection['id'],'e'=>$eventId]);$pdo->commit();http_response_code(204);
        }catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();$code=$e instanceof \DomainException?$e->getMessage():'processing_failed';$pdo->prepare("UPDATE tenant_payment_webhook_events SET status='failed',error_code=:code,processed_at=NOW() WHERE connection_id=:c AND event_id=:e")->execute(['code'=>substr($code,0,80),'c'=>$connection['id'],'e'=>$eventId]);error_log('[ApPlanner Payments Webhook] '.$code);http_response_code($e instanceof \DomainException?422:500);}
    }

    private function processTransaction(\PDO $pdo,int $tenant,int $connection,string $remoteId,string $external,string $remoteStatus,?float $amount): void
    {
        $tx=$pdo->prepare("SELECT * FROM tenant_payment_transactions WHERE tenant_id=:tenant AND connection_id=:connection AND (provider_transaction_id=:remote OR external_reference=:external) ORDER BY id DESC LIMIT 1 FOR UPDATE");
        $tx->execute(['tenant'=>$tenant,'connection'=>$connection,'remote'=>$remoteId,'external'=>$external!==''?$external:'__not_found__']);$transaction=$tx->fetch();if(!$transaction)throw new \DomainException('transaction_not_found');
        if($amount!==null&&abs($amount-(float)$transaction['gross_amount'])>0.01)throw new \DomainException('amount_mismatch');
        $mapped=$this->mapStatus($remoteStatus);$pdo->prepare("UPDATE tenant_payment_transactions SET provider_transaction_id=COALESCE(NULLIF(:remote,''),provider_transaction_id),status=:status,paid_at=IF(:paid='paid',COALESCE(paid_at,NOW()),paid_at),reconciled_at=IF(:paid2='paid',COALESCE(reconciled_at,NOW()),reconciled_at),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")->execute(['remote'=>$remoteId,'status'=>$mapped,'paid'=>$mapped,'paid2'=>$mapped,'id'=>$transaction['id'],'tenant'=>$tenant]);
        $transaction['provider_transaction_id']=$remoteId;
        if($mapped==='paid')$this->applyPaid($pdo,$transaction);elseif(in_array($mapped,['failed','cancelled','expired','refunded'],true))$this->applyTerminal($pdo,$transaction,$mapped);
    }

    private function processSubscription(\PDO $pdo,int $tenant,int $connection,string $remoteId,string $external,string $status): void
    {
        $q=$pdo->prepare("SELECT * FROM tenant_recurring_subscriptions WHERE tenant_id=:t AND connection_id=:c AND (provider_subscription_id=:provider OR external_reference=:external) ORDER BY id DESC LIMIT 1 FOR UPDATE");
        $q->execute(['t'=>$tenant,'c'=>$connection,'provider'=>$remoteId,'external'=>$external!==''?$external:'__not_found__']);$row=$q->fetch();if(!$row)throw new \DomainException('recurring_subscription_not_found');
        $mapped=$this->mapSubscriptionStatus($status);$pdo->prepare("UPDATE tenant_recurring_subscriptions SET provider_subscription_id=COALESCE(NULLIF(:provider,''),provider_subscription_id),status=:status,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['provider'=>$remoteId,'status'=>$mapped,'id'=>$row['id'],'t'=>$tenant]);
        if($row['reference_type']==='customer_membership'){$providerStatus=$mapped;$membershipStatus=$mapped==='cancelled'?'cancelled':'active';$pdo->prepare("UPDATE customer_memberships SET provider_subscription_id=COALESCE(NULLIF(:provider,''),provider_subscription_id),provider_status=:provider_status,status=IF(:cancelled='cancelled','cancelled',status),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['provider'=>$remoteId,'provider_status'=>$providerStatus,'cancelled'=>$membershipStatus,'id'=>$row['reference_id'],'t'=>$tenant]);}
    }

    private function processMembershipPayment(\PDO $pdo,int $tenant,int $connection,string $remoteId,string $external,string $remoteStatus,?float $amount,array $remote): void
    {
        BarberMembershipPaymentService::process($pdo,$tenant,$connection,$remoteId,$external,$remoteStatus,$amount,$remote);
    }

    private function fetchRemote(MercadoPagoProvider $provider,string $dataId,string $type): array
    {
        $kind=mb_strtolower($type);
        if(str_contains($kind,'subscription_authorized_payment'))return $provider->getAuthorizedPayment($dataId);
        if(str_contains($kind,'subscription_preapproval')||str_contains($kind,'preapproval'))return $provider->getSubscription($dataId);
        if(str_contains($kind,'payment')){try{return $provider->getPayment($dataId);}catch(\Throwable){return $provider->getOrder($dataId);}}
        try{return $provider->getOrder($dataId);}catch(\Throwable){try{return $provider->getPayment($dataId);}catch(\Throwable){return $provider->getSubscription($dataId);}}
    }
    private function isSubscriptionPreapprovalEvent(string $type,array $remote):bool{$kind=mb_strtolower($type);return str_contains($kind,'subscription_preapproval')||(!str_contains($kind,'authorized_payment')&&(str_contains($kind,'preapproval')||isset($remote['auto_recurring'])));}
    private function isAuthorizedSubscriptionPaymentEvent(string $type):bool{return str_contains(mb_strtolower($type),'subscription_authorized_payment');}
    private function remoteStatus(array $remote,string $type):string{$kind=mb_strtolower($type);if(str_contains($kind,'subscription_authorized_payment')){$nested=$remote['payment']['status']??null;if(is_string($nested)&&$nested!=='')return mb_strtolower($nested);}return mb_strtolower((string)($remote['status']??''));}
    private function isBarberMembershipPayment(string $external):bool{return str_starts_with($external,'BARBER-MEMBERSHIP-');}
    private function remoteAmount(array $remote):?float{foreach(['transaction_amount','total_amount'] as $key)if(isset($remote[$key])&&is_numeric($remote[$key]))return round((float)$remote[$key],2);$payments=$remote['transactions']['payments']??null;if(is_array($payments)&&isset($payments[0]['amount'])&&is_numeric($payments[0]['amount']))return round((float)$payments[0]['amount'],2);return null;}
    private function mapStatus(string $status):string{if(in_array($status,['approved','processed','paid','authorized'],true))return'paid';if(in_array($status,['cancelled','canceled'],true))return'cancelled';if(in_array($status,['refunded','charged_back'],true))return'refunded';if($status==='expired')return'expired';if(in_array($status,['rejected','failed'],true))return'failed';return'pending';}
    private function mapSubscriptionStatus(string $status):string{if(in_array($status,['authorized','approved','active'],true))return'authorized';if(in_array($status,['cancelled','canceled'],true))return'cancelled';if($status==='paused')return'paused';if(in_array($status,['failed','rejected'],true))return'failed';return'pending';}

    private function applyPaid(\PDO $pdo,array $tx):void
    {
        $tenant=(int)$tx['tenant_id'];$reference=(int)$tx['reference_id'];$amount=(float)$tx['gross_amount'];
        if($tx['reference_type']==='reservation'){$q=$pdo->prepare('SELECT total_amount,deposit_amount,status FROM sports_reservations WHERE id=:id AND tenant_id=:tenant FOR UPDATE');$q->execute(['id'=>$reference,'tenant'=>$tenant]);$reservation=$q->fetch();if(!$reservation)throw new \DomainException('reservation_not_found');$state=$amount+0.01>=(float)$reservation['total_amount']?'paid':'partial';$pdo->prepare("UPDATE sports_reservation_finance SET payment_state=:state,amount_paid=GREATEST(amount_paid,:amount),provider='mercadopago',external_reference=:external,transaction_id=:transaction,paid_at=COALESCE(paid_at,NOW()),reconciled_at=NOW(),updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant")->execute(['state'=>$state,'amount'=>$amount,'external'=>$tx['external_reference'],'transaction'=>$tx['provider_transaction_id']??null,'id'=>$reference,'tenant'=>$tenant]);$pdo->prepare("UPDATE sports_reservations SET status=IF(status='pending_payment','confirmed',status),payment_status='paid',confirmed_at=COALESCE(confirmed_at,NOW()),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")->execute(['id'=>$reference,'tenant'=>$tenant]);$pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,created_at) VALUES(:r,'payment_confirmed',:old,'confirmed','Pagamento validado pelo provedor',NOW())")->execute(['r'=>$reference,'old'=>$reservation['status']]);$this->financeIncome($pdo,$tenant,'arena_reservation',$reference,'Sinal de reserva Arena #'.$reference,$amount,(string)($tx['method']??'pix'));}
        elseif($tx['reference_type']==='game_player'){$q=$pdo->prepare('SELECT game_id,payment_status FROM sports_game_players WHERE id=:id AND tenant_id=:tenant FOR UPDATE');$q->execute(['id'=>$reference,'tenant'=>$tenant]);$player=$q->fetch();if(!$player)throw new \DomainException('player_not_found');$pdo->prepare("UPDATE sports_game_players SET payment_status='paid',amount_paid=:amount,paid_at=COALESCE(paid_at,NOW()),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")->execute(['amount'=>$amount,'id'=>$reference,'tenant'=>$tenant]);$this->financeIncome($pdo,$tenant,'arena_game_player',$reference,'Participação em racha #'.(int)$player['game_id'],$amount,(string)($tx['method']??'pix'));}
    }
    private function applyTerminal(\PDO $pdo,array $tx,string $status):void{$tenant=(int)$tx['tenant_id'];$reference=(int)$tx['reference_id'];if($tx['reference_type']==='reservation'){$state=$status==='refunded'?'refunded':($status==='expired'?'expired':($status==='failed'?'failed':'cancelled'));$pdo->prepare('UPDATE sports_reservation_finance SET payment_state=:state,updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant')->execute(['state'=>$state,'id'=>$reference,'tenant'=>$tenant]);if(in_array($status,['expired','cancelled'],true))$pdo->prepare("UPDATE sports_reservations SET status=IF(status='pending_payment','cancelled',status),payment_status=IF(payment_status='pending','cancelled',payment_status),cancelled_at=IF(status='pending_payment',NOW(),cancelled_at),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")->execute(['id'=>$reference,'tenant'=>$tenant]);}elseif($tx['reference_type']==='game_player'&&in_array($status,['cancelled','expired','failed'],true))$pdo->prepare("UPDATE sports_game_players SET payment_status='cancelled',updated_at=NOW() WHERE id=:id AND tenant_id=:tenant AND payment_status='pending'")->execute(['id'=>$reference,'tenant'=>$tenant]);}
    private function financeIncome(\PDO $pdo,int $tenant,string $sourceType,int $sourceId,string $description,float $amount,string $method):void{$q=$pdo->prepare("SELECT COALESCE(tm.enabled,pm.enabled,0) FROM subscriptions s JOIN modules m ON m.slug='finance' AND m.active=1 LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id LEFT JOIN tenant_modules tm ON tm.tenant_id=s.tenant_id AND tm.module_id=m.id WHERE s.tenant_id=:tenant ORDER BY s.id DESC LIMIT 1");$q->execute(['tenant'=>$tenant]);if(!(bool)$q->fetchColumn())return;$pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,competence_at,paid_at,created_at,updated_at) VALUES(:tenant,:source_type,:source_id,'income',:description,:amount,:method,'paid',:key,CURDATE(),NOW(),NOW(),NOW())")->execute(['tenant'=>$tenant,'source_type'=>$sourceType,'source_id'=>$sourceId,'description'=>$description,'amount'=>round($amount,2),'method'=>$method,'key'=>$sourceType.'-'.$sourceId]);}
}
