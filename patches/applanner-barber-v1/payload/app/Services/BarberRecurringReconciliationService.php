<?php
namespace App\Services;

use App\Core\{Database,Encryption};

final class BarberRecurringReconciliationService
{
    public function run(?int $tenantId=null): array
    {
        $pdo=Database::connection();$params=[];$sql="SELECT rs.*,pc.credentials_encrypted,pc.status connection_status,cm.status membership_status FROM tenant_recurring_subscriptions rs JOIN tenant_payment_connections pc ON pc.id=rs.connection_id AND pc.tenant_id=rs.tenant_id JOIN customer_memberships cm ON cm.id=rs.reference_id AND cm.tenant_id=rs.tenant_id WHERE rs.reference_type='customer_membership' AND rs.status IN('pending','authorized') AND cm.status='active' AND cm.billing_mode='provider' AND pc.provider='mercadopago' AND pc.status='connected'";if($tenantId){$sql.=' AND rs.tenant_id=:tenant';$params['tenant']=$tenantId;}$sql.=' ORDER BY rs.id';$q=$pdo->prepare($sql);$q->execute($params);$rows=$q->fetchAll();$checked=0;$applied=0;$errors=0;
        foreach($rows as $row){$checked++;try{$credentials=Encryption::decrypt((string)$row['credentials_encrypted']);$provider=new MercadoPagoProvider((string)($credentials['access_token']??''));$payments=$provider->searchPaymentsByExternalReference((string)$row['external_reference'],120);foreach($payments as $payment){$status=mb_strtolower((string)($payment['status']??''));if(!in_array($status,['approved','processed','paid','authorized'],true))continue;$remoteId=(string)($payment['id']??'');if($remoteId==='')continue;$amount=isset($payment['transaction_amount'])&&is_numeric($payment['transaction_amount'])?round((float)$payment['transaction_amount'],2):null;$pdo->beginTransaction();try{$did=BarberMembershipPaymentService::process($pdo,(int)$row['tenant_id'],(int)$row['connection_id'],$remoteId,(string)$row['external_reference'],$status,$amount,$payment);$pdo->commit();if($did)$applied++;}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();if($e instanceof \DomainException&&in_array($e->getMessage(),['membership_not_active'],true))continue;throw $e;}}}catch(\Throwable $e){$errors++;error_log('[ApPlanner Barber Recurring] subscription='.(int)$row['id'].' '.mb_substr($e->getMessage(),0,180));}}
        return ['recurring_checked'=>$checked,'recurring_payments_applied'=>$applied,'recurring_errors'=>$errors];
    }
}
