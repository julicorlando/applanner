<?php
namespace App\Services;

use App\Core\Database;

final class ReferralAttributionService
{
    public static function attributeCurrentUser(?array $user):void
    {
        if(!$user||empty($user['tenant_id'])||($user['role']??'')!=='owner')return;$token=(string)($_COOKIE['ap_ref']??'');if(!preg_match('/^[a-f0-9]{64}$/',$token))return;
        try{$pdo=Database::connection();$hash=hash('sha256',$token);$find=$pdo->prepare("SELECT rv.id,rv.referrer_user_id,cp.commission_percent,s.contracted_price FROM marketing_referral_visits rv LEFT JOIN commercial_profiles cp ON cp.user_id=rv.referrer_user_id AND cp.active=1 JOIN tenants t ON t.id=:tenant LEFT JOIN subscriptions s ON s.tenant_id=t.id WHERE rv.visit_token_hash=:hash AND rv.converted_tenant_id IS NULL AND rv.clicked_at>=DATE_SUB(NOW(),INTERVAL 30 DAY) AND t.created_at>=DATE_SUB(NOW(),INTERVAL 1 DAY) ORDER BY s.id DESC LIMIT 1");$find->execute(['tenant'=>(int)$user['tenant_id'],'hash'=>$hash]);$visit=$find->fetch();if($visit){$pdo->beginTransaction();$q=$pdo->prepare('UPDATE marketing_referral_visits SET converted_tenant_id=:tenant,converted_at=NOW() WHERE id=:id AND converted_tenant_id IS NULL');$q->execute(['tenant'=>(int)$user['tenant_id'],'id'=>$visit['id']]);if($q->rowCount()>0&&!empty($visit['commission_percent'])){$base=(float)($visit['contracted_price']??0);$pdo->prepare("INSERT IGNORE INTO commercial_commissions(commercial_user_id,tenant_id,base_amount,commission_percent,commission_amount,status,created_at,updated_at)VALUES(:u,:t,:base,:percent,:amount,'projected',NOW(),NOW())")->execute(['u'=>$visit['referrer_user_id'],'t'=>(int)$user['tenant_id'],'base'=>$base,'percent'=>$visit['commission_percent'],'amount'=>round($base*(float)$visit['commission_percent']/100,2)]);}$pdo->commit();setcookie('ap_ref','',['expires'=>time()-3600,'path'=>'/','secure'=>!empty($_SERVER['HTTPS'])&&$_SERVER['HTTPS']!=='off','httponly'=>true,'samesite'=>'Lax']);}}catch(\Throwable){if(isset($pdo)&&$pdo->inTransaction())$pdo->rollBack();}
    }
}
