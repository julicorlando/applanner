<?php
namespace App\Services;

use App\Core\Database;

final class PlatformMetricsService
{
    public static function calculate(): array
    {
        $pdo=Database::connection();
        $realTenant="COALESCE(t.is_demo,0)=0";
        $subs=$pdo->query("SELECT s.*,t.status tenant_status,t.created_at tenant_created_at,p.name plan_name
            FROM subscriptions s
            JOIN tenants t ON t.id=s.tenant_id AND t.deleted_at IS NULL AND COALESCE(t.is_demo,0)=0
            JOIN plans p ON p.id=s.plan_id
            WHERE s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=s.tenant_id)")->fetchAll();

        $mrrPlans=0.0;$trialPotential=0.0;$forecast30=0.0;$active=0;$trials=0;$cancelled30=0;$now=time();$limit30=strtotime('+30 days');
        foreach($subs as $s){
            $months=['monthly'=>1,'quarterly'=>3,'semiannual'=>6,'annual'=>12][$s['billing_cycle']]??1;
            $price=(float)($s['contracted_price']??0);$monthly=$price/max(1,$months);
            if($s['status']==='active'){$active++;$mrrPlans+=$monthly;}
            elseif($s['status']==='trial'){$trials++;$trialPotential+=$monthly;}
            if(in_array($s['status'],['active','trial'],true)&&!empty($s['next_billing_at'])){
                $due=strtotime($s['next_billing_at']);if($due>=$now&&$due<=$limit30)$forecast30+=$price;
            }
            if($s['status']==='cancelled'&&!empty($s['updated_at'])&&strtotime($s['updated_at'])>=strtotime('-30 days'))$cancelled30++;
        }

        $addonMrr=(float)$pdo->query("SELECT COALESCE(SUM(a.monthly_price),0)
            FROM tenant_module_addons a JOIN tenants t ON t.id=a.tenant_id
            WHERE a.status='active' AND COALESCE(t.is_demo,0)=0")->fetchColumn();
        $legacyAddonMrr=(float)$pdo->query("SELECT COALESCE(SUM(a.monthly_price),0)
            FROM tenant_module_addons a JOIN tenants t ON t.id=a.tenant_id
            WHERE a.status='active' AND COALESCE(a.billing_mode,'separate')='separate' AND COALESCE(t.is_demo,0)=0")->fetchColumn();
        $addonForecast=(float)$pdo->query("SELECT COALESCE(SUM(a.monthly_price),0)
            FROM tenant_module_addons a JOIN tenants t ON t.id=a.tenant_id
            WHERE a.status='active' AND COALESCE(a.billing_mode,'separate')='separate'
              AND (a.next_billing_at IS NULL OR a.next_billing_at<=DATE_ADD(NOW(),INTERVAL 30 DAY))
              AND COALESCE(t.is_demo,0)=0")->fetchColumn();

        $mrr=$mrrPlans+$legacyAddonMrr;$arr=$mrr*12;$forecast30+=$addonForecast;

        $receivedMonth=(float)$pdo->query("SELECT COALESCE(SUM(p.amount),0)
            FROM payments p JOIN tenants t ON t.id=p.tenant_id
            WHERE p.status='paid' AND COALESCE(p.environment,'unknown')<>'sandbox'
              AND p.paid_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01') AND COALESCE(t.is_demo,0)=0")->fetchColumn();
        $receivedToday=(float)$pdo->query("SELECT COALESCE(SUM(p.amount),0)
            FROM payments p JOIN tenants t ON t.id=p.tenant_id
            WHERE p.status='paid' AND COALESCE(p.environment,'unknown')<>'sandbox'
              AND DATE(p.paid_at)=CURDATE() AND COALESCE(t.is_demo,0)=0")->fetchColumn();

        $manualIncome=(float)$pdo->query("SELECT COALESCE(SUM(amount),0) FROM platform_financial_transactions
            WHERE type='income' AND status='paid' AND paid_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')")->fetchColumn();
        $expensesMonth=(float)$pdo->query("SELECT COALESCE(SUM(amount),0) FROM platform_financial_transactions
            WHERE type='expense' AND status='paid' AND paid_at>=DATE_FORMAT(CURDATE(),'%Y-%m-01')")->fetchColumn();

        $receivable=(float)$pdo->query("SELECT COALESCE(SUM(i.amount),0)
            FROM invoices i JOIN tenants t ON t.id=i.tenant_id
            WHERE i.status IN('pending','overdue') AND COALESCE(t.is_demo,0)=0")->fetchColumn();
        $payable=(float)$pdo->query("SELECT COALESCE(SUM(amount),0) FROM platform_financial_transactions
            WHERE type='expense' AND status='pending'")->fetchColumn();

        $tenants=(int)$pdo->query("SELECT COUNT(*) FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=0")->fetchColumn();
        $endCustomers=(int)$pdo->query("SELECT COUNT(*) FROM customers c JOIN tenants t ON t.id=c.tenant_id
            WHERE c.status='active' AND COALESCE(t.is_demo,0)=0")->fetchColumn();
        $new30=(int)$pdo->query("SELECT COUNT(*) FROM tenants
            WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=0 AND created_at>=DATE_SUB(NOW(),INTERVAL 30 DAY)")->fetchColumn();
        $modulePending=(int)$pdo->query("SELECT COUNT(*) FROM module_requests mr JOIN tenants t ON t.id=mr.tenant_id
            WHERE mr.status='pending' AND COALESCE(t.is_demo,0)=0")->fetchColumn();

        $churnBase=$active+$cancelled30;$churn=$churnBase>0?($cancelled30/$churnBase)*100:0;
        return [
            'tenants'=>$tenants,'active_subscriptions'=>$active,'trials'=>$trials,'end_customers'=>$endCustomers,'new_30d'=>$new30,
            'mrr'=>$mrr,'plan_mrr'=>$mrrPlans,'addon_mrr'=>$addonMrr,'arr'=>$arr,'trial_potential_mrr'=>$trialPotential,'forecast_30d'=>$forecast30,
            'arpa'=>$active>0?$mrr/$active:0,'received_month'=>$receivedMonth+$manualIncome,'received_today'=>$receivedToday,'expenses_month'=>$expensesMonth,
            'net_month'=>$receivedMonth+$manualIncome-$expensesMonth,'receivable'=>$receivable,'payable'=>$payable,'churn_30d'=>$churn,'module_requests_pending'=>$modulePending,
        ];
    }
}
