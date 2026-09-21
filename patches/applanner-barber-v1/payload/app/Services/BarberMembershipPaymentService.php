<?php
namespace App\Services;

final class BarberMembershipPaymentService
{
    public static function process(\PDO $pdo,int $tenant,int $connection,string $remoteId,string $external,string $remoteStatus,?float $amount,array $remote=[]): bool
    {
        $q=$pdo->prepare("SELECT rs.*,cm.customer_id,cm.package_id,cm.cycle,cm.recurring_amount,cm.status membership_status,sp.name package_name,sp.validity_days,c.name customer_name FROM tenant_recurring_subscriptions rs JOIN customer_memberships cm ON cm.id=rs.reference_id AND cm.tenant_id=rs.tenant_id JOIN service_packages sp ON sp.id=cm.package_id AND sp.tenant_id=cm.tenant_id JOIN customers c ON c.id=cm.customer_id AND c.tenant_id=cm.tenant_id WHERE rs.tenant_id=:t AND rs.connection_id=:c AND rs.reference_type='customer_membership' AND rs.external_reference=:external ORDER BY rs.id DESC LIMIT 1 FOR UPDATE");
        $q->execute(['t'=>$tenant,'c'=>$connection,'external'=>$external]);$row=$q->fetch();if(!$row)throw new \DomainException('membership_subscription_not_found');
        $mapped=self::mapStatus($remoteStatus);if($amount!==null&&$mapped==='paid'&&abs($amount-(float)$row['amount'])>0.01)throw new \DomainException('membership_amount_mismatch');
        if($mapped!=='paid'){$providerStatus=in_array($mapped,['failed','cancelled','expired','refunded'],true)?$mapped:'pending';$pdo->prepare("UPDATE customer_memberships SET provider_status=:status,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['status'=>$providerStatus,'id'=>$row['reference_id'],'t'=>$tenant]);return false;}
        if($row['membership_status']!=='active')throw new \DomainException('membership_not_active');
        $paid=round($amount??(float)$row['amount'],2);$paymentMeta=is_array($remote['payment']??null)?$remote['payment']:[];$method=(string)($paymentMeta['payment_type_id']??$paymentMeta['payment_method_id']??$remote['payment_type_id']??$remote['payment_method_id']??'mercadopago');$key='barber-membership-provider-'.$remoteId;$seen=$pdo->prepare('SELECT id FROM financial_transactions WHERE tenant_id=:t AND idempotency_key=:key LIMIT 1');$seen->execute(['t'=>$tenant,'key'=>$key]);if($seen->fetchColumn())return false;
        $pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,competence_at,paid_at,created_at,updated_at) VALUES(:t,'membership',:source,'income',:description,:amount,:method,'paid',:key,CURDATE(),NOW(),NOW(),NOW())")->execute(['t'=>$tenant,'source'=>$row['reference_id'],'description'=>'Mensalidade '.$row['package_name'].' — '.$row['customer_name'],'amount'=>$paid,'method'=>mb_substr($method,0,40),'key'=>$key]);
        $ft=$pdo->prepare('SELECT id FROM financial_transactions WHERE tenant_id=:t AND idempotency_key=:key LIMIT 1');$ft->execute(['t'=>$tenant,'key'=>$key]);$financeId=(int)$ft->fetchColumn();if(!$financeId)throw new \RuntimeException('membership_finance_not_found');
        $exists=$pdo->prepare('SELECT id FROM customer_packages WHERE tenant_id=:t AND membership_id=:m AND financial_transaction_id=:f LIMIT 1');$exists->execute(['t'=>$tenant,'m'=>$row['reference_id'],'f'=>$financeId]);
        if(!$exists->fetchColumn()){$expires=$row['validity_days']?(new \DateTimeImmutable('+'.(int)$row['validity_days'].' days'))->format('Y-m-d H:i:s'):null;$pdo->prepare("INSERT INTO customer_packages(tenant_id,customer_id,package_id,purchased_at,expires_at,status,paid_amount,membership_id,financial_transaction_id,created_at) VALUES(:t,:customer,:package,NOW(),:expires,'active',:amount,:membership,:finance,NOW())")->execute(['t'=>$tenant,'customer'=>$row['customer_id'],'package'=>$row['package_id'],'expires'=>$expires,'amount'=>$paid,'membership'=>$row['reference_id'],'finance'=>$financeId]);}
        $months=$row['cycle']==='quarterly'?3:1;$next=(new \DateTimeImmutable('today'))->modify('+'.$months.' months')->format('Y-m-d');$pdo->prepare("UPDATE customer_memberships SET provider_status='authorized',last_billed_at=CURDATE(),next_due_at=:next,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['next'=>$next,'id'=>$row['reference_id'],'t'=>$tenant]);$pdo->prepare("UPDATE tenant_recurring_subscriptions SET status='authorized',last_payment_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>$row['id'],'t'=>$tenant]);return true;
    }

    public static function mapStatus(string $status):string
    {
        $status=mb_strtolower($status);if(in_array($status,['approved','processed','paid','authorized'],true))return'paid';if(in_array($status,['cancelled','canceled'],true))return'cancelled';if(in_array($status,['refunded','charged_back'],true))return'refunded';if($status==='expired')return'expired';if(in_array($status,['rejected','failed'],true))return'failed';return'pending';
    }
}
