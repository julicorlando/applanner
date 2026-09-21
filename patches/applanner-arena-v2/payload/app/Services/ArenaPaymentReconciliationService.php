<?php
namespace App\Services;

use App\Core\Database;

final class ArenaPaymentReconciliationService
{
    public function apply(int $transactionId, string $mappedStatus, ?float $feeAmount = null, ?float $netAmount = null): void
    {
        $pdo=Database::connection();
        $pdo->beginTransaction();
        try {
            $q=$pdo->prepare('SELECT * FROM tenant_payment_transactions WHERE id=:id FOR UPDATE');
            $q->execute(['id'=>$transactionId]); $tx=$q->fetch();
            if(!$tx) throw new \DomainException('transaction_not_found');
            $params=['status'=>$mappedStatus,'id'=>$transactionId,'tenant'=>$tx['tenant_id']];
            $set="status=:status,paid_at=IF(:paid='paid',COALESCE(paid_at,NOW()),paid_at),reconciled_at=IF(:paid2='paid',COALESCE(reconciled_at,NOW()),reconciled_at),updated_at=NOW()";
            $params['paid']=$mappedStatus;$params['paid2']=$mappedStatus;
            if($feeAmount!==null){$set.=',fee_amount=:fee';$params['fee']=round(max(0,$feeAmount),2);} if($netAmount!==null){$set.=',net_amount=:net';$params['net']=round(max(0,$netAmount),2);}
            $pdo->prepare("UPDATE tenant_payment_transactions SET $set WHERE id=:id AND tenant_id=:tenant")->execute($params);
            $tx['status']=$mappedStatus;
            if($mappedStatus==='paid') $this->applyPaid($pdo,$tx);
            elseif(in_array($mappedStatus,['failed','cancelled','expired','refunded'],true)) $this->applyTerminal($pdo,$tx,$mappedStatus);
            $pdo->commit();
        } catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
    }

    public function mapStatus(string $status): string
    {
        $status=mb_strtolower(trim($status));
        if(in_array($status,['approved','processed','paid'],true))return 'paid';
        if(in_array($status,['cancelled','canceled'],true))return 'cancelled';
        if(in_array($status,['refunded','charged_back'],true))return 'refunded';
        if($status==='expired')return 'expired';
        if(in_array($status,['rejected','failed'],true))return 'failed';
        return 'pending';
    }

    private function applyPaid(\PDO $pdo,array $tx):void
    {
        $tenant=(int)$tx['tenant_id'];$reference=(int)$tx['reference_id'];$amount=(float)$tx['gross_amount'];$method=(string)$tx['method'];
        if($tx['reference_type']==='reservation'){
            $q=$pdo->prepare('SELECT total_amount,deposit_amount,status FROM sports_reservations WHERE id=:id AND tenant_id=:tenant FOR UPDATE');$q->execute(['id'=>$reference,'tenant'=>$tenant]);$reservation=$q->fetch();if(!$reservation)throw new \DomainException('reservation_not_found');
            $paidBefore=$pdo->prepare('SELECT amount_paid FROM sports_reservation_finance WHERE reservation_id=:id AND tenant_id=:tenant FOR UPDATE');$paidBefore->execute(['id'=>$reference,'tenant'=>$tenant]);$existing=(float)$paidBefore->fetchColumn();
            $paidTotal=max($existing,$amount);$state=$paidTotal+0.01>=(float)$reservation['total_amount']?'paid':'partial';
            $pdo->prepare("UPDATE sports_reservation_finance SET payment_state=:state,amount_paid=:amount,provider='mercadopago',external_reference=:external,transaction_id=:transaction,paid_at=COALESCE(paid_at,NOW()),reconciled_at=NOW(),updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant")
                ->execute(['state'=>$state,'amount'=>$paidTotal,'external'=>$tx['external_reference'],'transaction'=>$tx['provider_transaction_id']??null,'id'=>$reference,'tenant'=>$tenant]);
            $pdo->prepare("UPDATE sports_reservations SET status=IF(status='pending_payment','confirmed',status),payment_status=IF(:state='paid','paid','partial'),confirmed_at=COALESCE(confirmed_at,NOW()),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['state'=>$state,'id'=>$reference,'tenant'=>$tenant]);
            $pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,created_at) VALUES(:r,'payment_confirmed',:old,'confirmed',:notes,NOW())")
                ->execute(['r'=>$reference,'old'=>$reservation['status'],'notes'=>'Pagamento '.$method.' validado pelo provedor']);
            $this->financeIncome($pdo,$tenant,'arena_reservation',$reference,'Pagamento de reserva Arena #'.$reference,$amount,$method);
        }elseif($tx['reference_type']==='game_player'){
            $q=$pdo->prepare('SELECT game_id FROM sports_game_players WHERE id=:id AND tenant_id=:tenant FOR UPDATE');$q->execute(['id'=>$reference,'tenant'=>$tenant]);$player=$q->fetch();if(!$player)throw new \DomainException('player_not_found');
            $pdo->prepare("UPDATE sports_game_players SET payment_status='paid',amount_paid=:amount,paid_at=COALESCE(paid_at,NOW()),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['amount'=>$amount,'id'=>$reference,'tenant'=>$tenant]);
            $this->financeIncome($pdo,$tenant,'arena_game_player',$reference,'Participação em racha #'.(int)$player['game_id'],$amount,$method);
        }
    }

    private function applyTerminal(\PDO $pdo,array $tx,string $status):void
    {
        $tenant=(int)$tx['tenant_id'];$reference=(int)$tx['reference_id'];
        if($tx['reference_type']==='reservation'){
            $state=$status==='refunded'?'refunded':($status==='expired'?'expired':($status==='failed'?'failed':'cancelled'));
            $pdo->prepare('UPDATE sports_reservation_finance SET payment_state=:state,updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant')->execute(['state'=>$state,'id'=>$reference,'tenant'=>$tenant]);
            if(in_array($status,['expired','cancelled'],true))$pdo->prepare("UPDATE sports_reservations SET status=IF(status='pending_payment','cancelled',status),payment_status=IF(payment_status='pending','cancelled',payment_status),cancelled_at=IF(status='pending_payment',NOW(),cancelled_at),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")->execute(['id'=>$reference,'tenant'=>$tenant]);
        }elseif($tx['reference_type']==='game_player'&&in_array($status,['cancelled','expired','failed'],true)){
            $pdo->prepare("UPDATE sports_game_players SET payment_status='cancelled',updated_at=NOW() WHERE id=:id AND tenant_id=:tenant AND payment_status='pending'")->execute(['id'=>$reference,'tenant'=>$tenant]);
        }
    }

    private function financeIncome(\PDO $pdo,int $tenant,string $sourceType,int $sourceId,string $description,float $amount,string $method):void
    {
        try{$enabled=ModuleService::has('finance',$tenant);}catch(\Throwable){$enabled=false;}if(!$enabled)return;
        $key=$sourceType.'-'.$sourceId.'-'.$method;
        $pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,competence_at,paid_at,created_at,updated_at) VALUES(:tenant,:source_type,:source_id,'income',:description,:amount,:method,'paid',:key,CURDATE(),NOW(),NOW(),NOW())")
            ->execute(['tenant'=>$tenant,'source_type'=>$sourceType,'source_id'=>$sourceId,'description'=>$description,'amount'=>round($amount,2),'method'=>$method,'key'=>$key]);
    }
}
