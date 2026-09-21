<?php
namespace App\Controllers;

use App\Core\{Auth,Database,View,Authorization,TenantContext};
use App\Services\{BehaviorEngine,ModuleService,ArenaTenantService,AutoTenantService};

final class DashboardController
{
    public function index(): void
    {
        Auth::requireLogin();$user=Auth::user();
        if(empty($user['tenant_id'])){header('Location: '.(($user['role']??'')==='master'?'/master':'/master/support'));exit;}
        Authorization::require('dashboard.view');$tenantId=TenantContext::id();
        if(ArenaTenantService::isArena($tenantId)){header('Location: /sports');exit;}
        if(AutoTenantService::isAutoTenant($tenantId)){header('Location: /auto');exit;}
        if(($user['role']??'')==='professional'){$this->professionalDashboard($tenantId);return;}
        $pdo=Database::connection();$stats=[];
        foreach([
            'customers'=>"SELECT COUNT(*) FROM customers WHERE tenant_id=:tenant_id AND status='active'",
            'services'=>"SELECT COUNT(*) FROM services WHERE tenant_id=:tenant_id AND active=1",
            'today'=>"SELECT COUNT(*) FROM appointments WHERE tenant_id=:tenant_id AND DATE(starts_at)=CURDATE() AND status NOT IN('cancelled')",
            'completed_month'=>"SELECT COUNT(*) FROM appointments WHERE tenant_id=:tenant_id AND status='completed' AND starts_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')",
            'cancelled_month'=>"SELECT COUNT(*) FROM appointments WHERE tenant_id=:tenant_id AND status='cancelled' AND starts_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')",
            'no_show_month'=>"SELECT COUNT(*) FROM appointments WHERE tenant_id=:tenant_id AND status='no_show' AND starts_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')",
        ] as $key=>$sql){$stmt=$pdo->prepare($sql);$stmt->execute(['tenant_id'=>$tenantId]);$stats[$key]=(int)$stmt->fetchColumn();}
        $q=$pdo->prepare("SELECT COALESCE(SUM(COALESCE(a.service_price_snapshot,s.price)),0) FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.tenant_id=:t AND a.status='completed' AND a.starts_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')");$q->execute(['t'=>$tenantId]);$stats['service_revenue_month']=(float)$q->fetchColumn();
        $stats['product_revenue_month']=0.0;if(ModuleService::has('products',$tenantId)){$q=$pdo->prepare("SELECT COALESCE(SUM(total),0) FROM sales WHERE tenant_id=:t AND status='completed' AND created_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')");$q->execute(['t'=>$tenantId]);$stats['product_revenue_month']=(float)$q->fetchColumn();}
        $stats['revenue_month']=$stats['service_revenue_month']+$stats['product_revenue_month'];$stats['ticket_average']=$stats['completed_month']>0?$stats['service_revenue_month']/$stats['completed_month']:0;
        $behaviorEnabled=ModuleService::has('behavior',$tenantId);$opportunities=$behaviorEnabled?(new BehaviorEngine())->opportunities($tenantId,5):[];$stats['opportunities']=count($opportunities);
        $stmt=$pdo->prepare("SELECT a.*,c.name customer_name,s.name service_name,p.name professional_name FROM appointments a JOIN customers c ON c.id=a.customer_id AND c.tenant_id=a.tenant_id JOIN services s ON s.id=a.service_id AND s.tenant_id=a.tenant_id LEFT JOIN professionals p ON p.id=a.professional_id WHERE a.tenant_id=:t AND a.starts_at>=NOW() ORDER BY a.starts_at LIMIT 8");$stmt->execute(['t'=>$tenantId]);
        $t=$pdo->prepare('SELECT name,public_slug,public_short_code,public_enabled,category FROM tenants WHERE id=:t');$t->execute(['t'=>$tenantId]);$tenant=$t->fetch();$barberMode=in_array(mb_strtolower(trim((string)($tenant['category']??''))),['barbearia','barber','barbershop'],true);
        if($barberMode){foreach(['open_commands'=>"SELECT COUNT(*) FROM barber_commands WHERE tenant_id=:t AND status='open'",'queue_waiting'=>"SELECT COUNT(*) FROM barber_queue_entries WHERE tenant_id=:t AND status IN('waiting','called')",'tips_month'=>"SELECT COALESCE(SUM(tip_amount),0) FROM barber_commands WHERE tenant_id=:t AND status='closed' AND closed_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')",'commissions_pending'=>"SELECT COALESCE(SUM(commission_amount),0) FROM professional_commissions WHERE tenant_id=:t AND status='pending'"] as $key=>$sql){$bq=$pdo->prepare($sql);$bq->execute(['t'=>$tenantId]);$stats[$key]=in_array($key,['tips_month','commissions_pending'],true)?(float)$bq->fetchColumn():(int)$bq->fetchColumn();}}
        View::render('dashboard/index',['title'=>'Dashboard','stats'=>$stats,'opportunities'=>$opportunities,'upcoming'=>$stmt->fetchAll(),'tenant'=>$tenant,'behaviorEnabled'=>$behaviorEnabled,'productsEnabled'=>ModuleService::has('products',$tenantId),'barberMode'=>$barberMode]);
    }

    private function professionalDashboard(int $tenantId):void
    {
        $pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM professionals WHERE tenant_id=:t AND user_id=:u AND active=1');$q->execute(['t'=>$tenantId,'u'=>Auth::user()['id']]);$professional=$q->fetch();if(!$professional){\App\Core\HttpException::abort(403,'Seu usuário não está vinculado a um profissional ativo.');}
        $q=$pdo->prepare("SELECT a.*,c.name customer_name,s.name service_name FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN services s ON s.id=a.service_id WHERE a.tenant_id=:t AND a.professional_id=:p AND a.starts_at>=CURDATE() ORDER BY a.starts_at LIMIT 12");$q->execute(['t'=>$tenantId,'p'=>$professional['id']]);$appointments=$q->fetchAll();
        $q=$pdo->prepare("SELECT COUNT(*) qty,COALESCE(SUM(COALESCE(a.service_price_snapshot,s.price)),0) revenue FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.tenant_id=:t AND a.professional_id=:p AND a.status='completed' AND a.starts_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')");$q->execute(['t'=>$tenantId,'p'=>$professional['id']]);$service=$q->fetch();
        $sales=['qty'=>0,'revenue'=>0];$productsEnabled=ModuleService::has('products',$tenantId);if($productsEnabled){$q=$pdo->prepare("SELECT COUNT(*) qty,COALESCE(SUM(total),0) revenue FROM sales WHERE tenant_id=:t AND professional_id=:p AND status='completed' AND created_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')");$q->execute(['t'=>$tenantId,'p'=>$professional['id']]);$sales=$q->fetch();}
        $q=$pdo->prepare('SELECT name,public_slug,public_short_code FROM tenants WHERE id=:t');$q->execute(['t'=>$tenantId]);$tenant=$q->fetch();
        View::render('dashboard/professional',['title'=>'Meu painel','professional'=>$professional,'tenant'=>$tenant,'appointments'=>$appointments,'service'=>$service,'sales'=>$sales,'productsEnabled'=>$productsEnabled]);
    }
}
