<?php
namespace App\Services;
use App\Core\{Database,HttpException};
final class SubscriptionExemptionService
{
 public static function current(int $tenantId):array|false
 {
  $pdo=Database::connection();$pdo->prepare("UPDATE subscription_exemptions SET status='expired',updated_at=NOW() WHERE tenant_id=:t AND status='active' AND ends_at IS NOT NULL AND ends_at<NOW()")->execute(['t'=>$tenantId]);$q=$pdo->prepare("SELECT se.*,u.name granted_by_name FROM subscription_exemptions se LEFT JOIN users u ON u.id=se.granted_by WHERE se.tenant_id=:t AND se.status='active' AND se.starts_at<=NOW() AND (se.ends_at IS NULL OR se.ends_at>=NOW()) ORDER BY se.id DESC LIMIT 1");$q->execute(['t'=>$tenantId]);return$q->fetch();
 }
 public static function requireChargeable(int $tenantId):void{if(self::current($tenantId))HttpException::abort(409,'Esta empresa possui isenção de mensalidade ativa e não precisa iniciar um pagamento.');}
}
