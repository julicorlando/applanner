<?php
namespace App\Services;

use App\Core\{Database,Encryption};

final class NotificationService
{
    public static function user(int $userId,?int $tenantId,string $type,string $title,string $message,?string $url=null,string $severity='info'):void
    {
        $pdo=Database::connection();$severity=in_array($severity,['info','success','warning','danger'],true)?$severity:'info';
        $pdo->prepare('INSERT INTO user_notifications(tenant_id,user_id,type,title,message,action_url,severity,created_at)VALUES(:t,:u,:type,:title,:message,:url,:severity,NOW())')->execute(['t'=>$tenantId,'u'=>$userId,'type'=>$type,'title'=>$title,'message'=>$message,'url'=>$url,'severity'=>$severity]);
    }
    public static function tenantOwners(int $tenantId,string $type,string $title,string $message,?string $url=null,string $severity='info'):void
    {
        $q=Database::connection()->prepare("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE u.tenant_id=:t AND u.status='active' AND r.slug IN('owner','manager')");$q->execute(['t'=>$tenantId]);foreach($q->fetchAll() as $u)self::user((int)$u['id'],$tenantId,$type,$title,$message,$url,$severity);
    }
    public static function professional(int $tenantId,int $professionalId,string $type,string $title,string $message,?string $url=null,string $severity='info'):void
    {
        $q=Database::connection()->prepare('SELECT user_id FROM professionals WHERE id=:p AND tenant_id=:t AND active=1');$q->execute(['p'=>$professionalId,'t'=>$tenantId]);$uid=(int)$q->fetchColumn();if($uid)self::user($uid,$tenantId,$type,$title,$message,$url,$severity);
    }
    public static function platformStaff(string $type,string $title,string $message,?string $url=null,string $severity='info'):void
    {
        $q=Database::connection()->query("SELECT DISTINCT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE u.tenant_id IS NULL AND u.status='active' AND r.slug IN('master','support')");
        foreach($q->fetchAll() as $u)self::user((int)$u['id'],null,$type,$title,$message,$url,$severity);
    }
    public static function queueExternal(int $tenantId,string $channel,string $destination,string $subject,string $message,array $meta=[]):void
    {
        $payload=Encryption::encrypt(['channel'=>$channel,'destination'=>$destination,'subject'=>$subject,'message'=>$message]+$meta);
        Database::connection()->prepare("INSERT INTO jobs(tenant_id,type,payload_encrypted,status,attempts,available_at,created_at,updated_at)VALUES(:t,'campaign.send',:p,'queued',0,NOW(),NOW(),NOW())")->execute(['t'=>$tenantId,'p'=>$payload]);
    }
}
