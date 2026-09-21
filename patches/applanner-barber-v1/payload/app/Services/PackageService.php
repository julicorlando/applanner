<?php
namespace App\Services;

use App\Core\Database;

final class PackageService
{
    public static function hasBalance(int $tenantId,int $customerId,int $serviceId):bool
    {
        if(!ModuleService::has('packages',$tenantId))return false;
        $q=Database::connection()->prepare("SELECT 1 FROM customer_packages cp JOIN service_package_items spi ON spi.package_id=cp.package_id AND spi.service_id=:s WHERE cp.tenant_id=:t AND cp.customer_id=:c AND cp.status='active' AND (cp.expires_at IS NULL OR cp.expires_at>=NOW()) AND (SELECT COALESCE(SUM(u.quantity),0) FROM customer_package_usage u WHERE u.customer_package_id=cp.id AND u.service_id=:s2)<spi.quantity LIMIT 1");
        $q->execute(['s'=>$serviceId,'s2'=>$serviceId,'t'=>$tenantId,'c'=>$customerId]);
        return (bool)$q->fetchColumn();
    }

    public static function consumeForAppointment(int $tenantId,int $appointmentId,int $customerId,int $serviceId):bool
    {
        if(!ModuleService::has('packages',$tenantId))return false;
        $pdo=Database::connection();$ownTx=!$pdo->inTransaction();if($ownTx)$pdo->beginTransaction();
        try{
            $already=$pdo->prepare('SELECT 1 FROM customer_package_usage u JOIN customer_packages cp ON cp.id=u.customer_package_id WHERE cp.tenant_id=:t AND u.appointment_id=:a LIMIT 1');$already->execute(['t'=>$tenantId,'a'=>$appointmentId]);if($already->fetchColumn()){if($ownTx)$pdo->commit();return true;}
            $q=$pdo->prepare("SELECT cp.id,cp.package_id,spi.quantity included,(SELECT COALESCE(SUM(u.quantity),0) FROM customer_package_usage u WHERE u.customer_package_id=cp.id AND u.service_id=:service_used) used FROM customer_packages cp JOIN service_package_items spi ON spi.package_id=cp.package_id AND spi.service_id=:service_item WHERE cp.tenant_id=:t AND cp.customer_id=:c AND cp.status='active' AND (cp.expires_at IS NULL OR cp.expires_at>=NOW()) HAVING used<included ORDER BY COALESCE(cp.expires_at,'9999-12-31 23:59:59'),cp.id LIMIT 1 FOR UPDATE");
            $q->execute(['service_used'=>$serviceId,'service_item'=>$serviceId,'t'=>$tenantId,'c'=>$customerId]);$cp=$q->fetch();if(!$cp){if($ownTx)$pdo->commit();return false;}
            $pdo->prepare('INSERT INTO customer_package_usage(customer_package_id,service_id,appointment_id,quantity,created_at)VALUES(:cp,:s,:a,1,NOW())')->execute(['cp'=>$cp['id'],'s'=>$serviceId,'a'=>$appointmentId]);
            self::refreshStatus($pdo,(int)$cp['id'],(int)$cp['package_id']);
            if($ownTx)$pdo->commit();return true;
        }catch(\Throwable $e){if($ownTx&&$pdo->inTransaction())$pdo->rollBack();throw $e;}
    }

    public static function reverseAppointment(int $tenantId,int $appointmentId):void
    {
        if(!ModuleService::has('packages',$tenantId))return;$pdo=Database::connection();$ownTx=!$pdo->inTransaction();if($ownTx)$pdo->beginTransaction();
        try{$q=$pdo->prepare('SELECT u.id,u.customer_package_id,cp.package_id FROM customer_package_usage u JOIN customer_packages cp ON cp.id=u.customer_package_id WHERE cp.tenant_id=:t AND u.appointment_id=:a FOR UPDATE');$q->execute(['t'=>$tenantId,'a'=>$appointmentId]);$rows=$q->fetchAll();foreach($rows as $r){$pdo->prepare('DELETE FROM customer_package_usage WHERE id=:id')->execute(['id'=>$r['id']]);$pdo->prepare("UPDATE customer_packages SET status='active' WHERE id=:id AND tenant_id=:t AND status='used'")->execute(['id'=>$r['customer_package_id'],'t'=>$tenantId]);self::refreshStatus($pdo,(int)$r['customer_package_id'],(int)$r['package_id']);}if($ownTx)$pdo->commit();}catch(\Throwable $e){if($ownTx&&$pdo->inTransaction())$pdo->rollBack();throw $e;}
    }

    private static function refreshStatus(\PDO $pdo,int $customerPackageId,int $packageId):void
    {
        $q=$pdo->prepare('SELECT COUNT(*) FROM service_package_items spi WHERE spi.package_id=:p AND (SELECT COALESCE(SUM(u.quantity),0) FROM customer_package_usage u WHERE u.customer_package_id=:cp AND u.service_id=spi.service_id)<spi.quantity');$q->execute(['p'=>$packageId,'cp'=>$customerPackageId]);$status=(int)$q->fetchColumn()===0?'used':'active';$pdo->prepare("UPDATE customer_packages SET status=:s WHERE id=:id AND status IN('active','used')")->execute(['s'=>$status,'id'=>$customerPackageId]);
    }
}
