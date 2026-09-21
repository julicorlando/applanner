<?php
namespace App\Core;
use App\Services\SubscriptionExemptionService;

final class SubscriptionAccess
{
    private const ALLOWED_PREFIXES=['/billing','/checkout','/security','/verify-email','/logout'];

    public static function enforce(): void
    {
        $user=Auth::user();
        if(!$user||Auth::isSupportImpersonating()||($user['role']??'')==='master'||empty($user['tenant_id']))return;
        $state=self::state((int)$user['tenant_id']);
        $_SESSION['access_mode']=$state;
        if(!$state['restricted'])return;
        $path=parse_url($_SERVER['REQUEST_URI']??'/',PHP_URL_PATH)?:'/';
        foreach(self::ALLOWED_PREFIXES as $allowed)if($path===$allowed||str_starts_with($path,$allowed.'/'))return;
        SecurityLogger::log('subscription.restricted_access',['path'=>$path,'reason'=>$state['reason']]);
        if(str_starts_with($path,'/api/')){http_response_code(402);header('Content-Type: application/json; charset=utf-8');echo json_encode(['success'=>false,'message'=>'Regularize sua assinatura para acessar este recurso.','data'=>['billing_url'=>'/billing']],JSON_UNESCAPED_UNICODE);exit;}
        $_SESSION['billing_notice']='Sua conta continua disponível. Regularize a assinatura para liberar os módulos operacionais.';
        header('Location: /billing');exit;
    }

    public static function state(int $tenantId): array
    {
        if($exemption=SubscriptionExemptionService::current($tenantId))return ['restricted'=>false,'reason'=>'exempt','status'=>'exempt','trial_ends_at'=>null,'next_billing_at'=>$exemption['ends_at'],'exemption'=>$exemption];
        $stmt=Database::connection()->prepare("SELECT t.status tenant_status,s.status subscription_status,s.trial_ends_at,s.next_billing_at FROM tenants t LEFT JOIN subscriptions s ON s.tenant_id=t.id WHERE t.id=:tenant ORDER BY s.id DESC LIMIT 1");
        $stmt->execute(['tenant'=>$tenantId]);$row=$stmt->fetch();
        if(!$row)return ['restricted'=>true,'reason'=>'subscription_missing','status'=>'missing'];
        $status=$row['subscription_status']??'missing';$trialExpired=$status==='trial'&&(!empty($row['trial_ends_at'])&&strtotime($row['trial_ends_at'])<time());
        $restricted=self::isRestricted((string)$row['tenant_status'],$status,$row['trial_ends_at']);
        $reason=$trialExpired?'trial_expired':($restricted?$status:'active');
        return ['restricted'=>$restricted,'reason'=>$reason,'status'=>$status,'trial_ends_at'=>$row['trial_ends_at'],'next_billing_at'=>$row['next_billing_at']];
    }

    public static function current(): array{return $_SESSION['access_mode']??['restricted'=>false,'reason'=>'active','status'=>'active'];}

    public static function isRestricted(string $tenantStatus,string $subscriptionStatus,?string $trialEndsAt=null):bool
    {
        $trialExpired=$subscriptionStatus==='trial'&&$trialEndsAt!==null&&strtotime($trialEndsAt)<time();
        return $trialExpired||in_array($subscriptionStatus,['past_due','suspended','cancelled','missing'],true)||in_array($tenantStatus,['suspended','cancelled'],true);
    }
}
