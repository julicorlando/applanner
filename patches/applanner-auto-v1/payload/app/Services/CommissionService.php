<?php
namespace App\Services;
use App\Core\Database;
final class CommissionService
{
    public static function service(int $tenantId,int $appointmentId):void
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT a.professional_id,a.service_id,COALESCE(a.service_price_snapshot,s.price) gross,p.commission_percent FROM appointments a JOIN services s ON s.id=a.service_id LEFT JOIN professionals p ON p.id=a.professional_id WHERE a.id=:id AND a.tenant_id=:t AND a.status='completed'");$q->execute(['id'=>$appointmentId,'t'=>$tenantId]);$r=$q->fetch();if(!$r||!$r['professional_id'])return;[$amount,$rate]=self::serviceAmount($tenantId,(int)$r['professional_id'],(int)$r['service_id'],(float)$r['gross'],(float)($r['commission_percent']??0));
        self::upsert($tenantId,(int)$r['professional_id'],'service',$appointmentId,(float)$r['gross'],$rate,$amount);
    }
    public static function product(int $tenantId,int $saleId):void
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT sa.professional_id,sa.total,p.commission_percent,COALESCE(SUM(si.commission_amount_snapshot),0) product_commission FROM sales sa LEFT JOIN professionals p ON p.id=sa.professional_id LEFT JOIN sale_items si ON si.sale_id=sa.id WHERE sa.id=:id AND sa.tenant_id=:t AND sa.status='completed' GROUP BY sa.id,sa.professional_id,sa.total,p.commission_percent");$q->execute(['id'=>$saleId,'t'=>$tenantId]);$r=$q->fetch();if(!$r||!$r['professional_id'])return;$specific=round((float)$r['product_commission'],2);$rate=(float)($r['commission_percent']??0);$amount=$specific>0?$specific:round((float)$r['total']*$rate/100,2);self::upsert($tenantId,(int)$r['professional_id'],'product',$saleId,(float)$r['total'],$specific>0?null:$rate,$amount);
    }
    public static function commandService(int $tenantId,int $itemId):void
    {
        $q=Database::connection()->prepare("SELECT i.professional_id,i.service_id,i.total_amount gross,p.commission_percent FROM barber_command_items i JOIN barber_commands c ON c.id=i.command_id LEFT JOIN professionals p ON p.id=i.professional_id WHERE i.id=:id AND i.tenant_id=:t AND c.status IN('open','closed') AND i.item_type='service'");$q->execute(['id'=>$itemId,'t'=>$tenantId]);$r=$q->fetch();if(!$r||!$r['professional_id'])return;[$amount,$rate]=self::serviceAmount($tenantId,(int)$r['professional_id'],(int)$r['service_id'],(float)$r['gross'],(float)($r['commission_percent']??0));self::upsert($tenantId,(int)$r['professional_id'],'command_service',$itemId,(float)$r['gross'],$rate,$amount);
    }
    public static function commandProduct(int $tenantId,int $itemId):void
    {
        $q=Database::connection()->prepare("SELECT professional_id,total_amount gross,commission_amount_snapshot amount FROM barber_command_items WHERE id=:id AND tenant_id=:t AND item_type='product'");$q->execute(['id'=>$itemId,'t'=>$tenantId]);$r=$q->fetch();if(!$r||!$r['professional_id'])return;$amount=round((float)($r['amount']??0),2);if($amount<=0)return;self::upsert($tenantId,(int)$r['professional_id'],'command_product',$itemId,(float)$r['gross'],null,$amount);
    }
    public static function tip(int $tenantId,int $commandId,int $professionalId,float $amount):void
    {if($amount<=0)return;self::upsert($tenantId,$professionalId,'tip',$commandId,$amount,100.0,round($amount,2));}
    public static function reverse(string $type,int $tenantId,int $sourceId):void{Database::connection()->prepare("UPDATE professional_commissions SET status='reversed',updated_at=NOW() WHERE tenant_id=:t AND source_type=:type AND source_id=:sid AND status<>'paid'")->execute(['t'=>$tenantId,'type'=>$type,'sid'=>$sourceId]);}
    private static function serviceAmount(int $tenantId,int $professionalId,int $serviceId,float $gross,float $fallback):array
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT commission_type,commission_value FROM professional_service_commissions WHERE tenant_id=:t AND professional_id=:p AND service_id=:s AND active=1 LIMIT 1");$q->execute(['t'=>$tenantId,'p'=>$professionalId,'s'=>$serviceId]);if($rule=$q->fetch()){if($rule['commission_type']==='fixed')return [round((float)$rule['commission_value'],2),null];$rate=(float)$rule['commission_value'];return [round($gross*$rate/100,2),$rate];}
        $q=$pdo->prepare('SELECT model,service_commission_percent FROM professional_compensation_models WHERE tenant_id=:t AND professional_id=:p');$q->execute(['t'=>$tenantId,'p'=>$professionalId]);$comp=$q->fetch();if($comp&&in_array($comp['model'],['chair_rent','daily_rent'],true))return [0.0,0.0];$override=$comp['service_commission_percent']??null;$rate=$override!==null?(float)$override:$fallback;return [round($gross*$rate/100,2),$rate];
    }
    private static function upsert(int $t,int $p,string $type,int $source,float $gross,?float $rate,float $amount):void
    {Database::connection()->prepare("INSERT INTO professional_commissions(tenant_id,professional_id,source_type,source_id,gross_amount,rate_percent,commission_amount,status,created_at,updated_at)VALUES(:t,:p,:type,:sid,:gross,:rate,:amount,'pending',NOW(),NOW()) ON DUPLICATE KEY UPDATE gross_amount=VALUES(gross_amount),rate_percent=VALUES(rate_percent),commission_amount=IF(status='pending',VALUES(commission_amount),commission_amount),updated_at=NOW()")->execute(['t'=>$t,'p'=>$p,'type'=>$type,'sid'=>$source,'gross'=>$gross,'rate'=>$rate,'amount'=>$amount]);}
}
