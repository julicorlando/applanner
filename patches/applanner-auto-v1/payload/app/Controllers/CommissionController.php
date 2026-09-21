<?php
namespace App\Controllers;
use App\Core\{Authorization,CSRF,Database,TenantContext,View,Audit,Auth,HttpException};
use App\Services\ModuleService;
final class CommissionController
{
    private function enabled():void{ModuleService::require('finance');}
    public function index():void{$this->enabled();Authorization::require('commissions.view');$t=TenantContext::id();$pdo=Database::connection();$professional=$this->professionalId($t);$q=$pdo->prepare("SELECT pc.*,p.name professional_name FROM professional_commissions pc JOIN professionals p ON p.id=pc.professional_id WHERE pc.tenant_id=:t AND (:p IS NULL OR pc.professional_id=:p2) ORDER BY pc.created_at DESC LIMIT 500");$q->execute(['t'=>$t,'p'=>$professional,'p2'=>$professional]);$items=$q->fetchAll();$summary=['pending'=>0,'paid'=>0,'reversed'=>0];foreach($items as $i)$summary[$i['status']]+=(float)$i['commission_amount'];View::render('commissions/index',['title'=>'Comissões','items'=>$items,'summary'=>$summary,'professional'=>$professional]);}
    public function pay(string $id):void
    {
        $this->enabled();Authorization::require('commissions.manage');CSRF::enforce();$t=TenantContext::id();$pdo=Database::connection();$pdo->beginTransaction();
        try{$q=$pdo->prepare("SELECT pc.*,p.name professional_name FROM professional_commissions pc JOIN professionals p ON p.id=pc.professional_id AND p.tenant_id=pc.tenant_id WHERE pc.id=:id AND pc.tenant_id=:t AND pc.status='pending' FOR UPDATE");$q->execute(['id'=>(int)$id,'t'=>$t]);$row=$q->fetch();if(!$row){$pdo->rollBack();HttpException::abort(404,'Comissão não encontrada ou já processada.');}$pdo->prepare("UPDATE professional_commissions SET status='paid',paid_at=NOW(),paid_by=:u,updated_at=NOW() WHERE id=:id AND tenant_id=:t AND status='pending'")->execute(['u'=>Auth::user()['id'],'id'=>$row['id'],'t'=>$t]);$this->financeExpense($pdo,$t,$row);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('commission.paid','professional_commissions',(int)$id);header('Location: /commissions');exit;
    }
    public function payPeriod():void
    {
        $this->enabled();Authorization::require('commissions.manage');CSRF::enforce();$t=TenantContext::id();$professional=(int)($_POST['professional_id']??0);$from=(string)($_POST['from']??'');$to=(string)($_POST['to']??'');if(!$professional||!preg_match('/^\d{4}-\d{2}-\d{2}$/',$from)||!preg_match('/^\d{4}-\d{2}-\d{2}$/',$to))HttpException::abort(422,'Período inválido.');$pdo=Database::connection();$pdo->beginTransaction();$count=0;
        try{$q=$pdo->prepare("SELECT pc.*,p.name professional_name FROM professional_commissions pc JOIN professionals p ON p.id=pc.professional_id AND p.tenant_id=pc.tenant_id WHERE pc.tenant_id=:t AND pc.professional_id=:p AND pc.status='pending' AND pc.created_at BETWEEN :f AND :to ORDER BY pc.id FOR UPDATE");$q->execute(['t'=>$t,'p'=>$professional,'f'=>$from.' 00:00:00','to'=>$to.' 23:59:59']);$rows=$q->fetchAll();$u=$pdo->prepare("UPDATE professional_commissions SET status='paid',paid_at=NOW(),paid_by=:u,updated_at=NOW() WHERE id=:id AND tenant_id=:t AND status='pending'");foreach($rows as $row){$u->execute(['u'=>Auth::user()['id'],'id'=>$row['id'],'t'=>$t]);if(!$u->rowCount())continue;$this->financeExpense($pdo,$t,$row);$count++;}$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('commission.period_paid','professional_commissions',null,null,['professional_id'=>$professional,'count'=>$count,'from'=>$from,'to'=>$to]);header('Location: /commissions');exit;
    }
    private function financeExpense(\PDO $pdo,int $tenant,array $row):void
    {
        $amount=round((float)$row['commission_amount'],2);if($amount<=0)return;$label=$row['source_type']==='tip'?'Gorjeta':'Comissão';$description=$label.' paga — '.(string)($row['professional_name']??('Profissional #'.(int)$row['professional_id']));$pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,status,idempotency_key,competence_at,paid_at,created_at,updated_at) VALUES(:t,'commission_payout',:source,'expense',:description,:amount,'paid',:key,CURDATE(),NOW(),NOW(),NOW())")->execute(['t'=>$tenant,'source'=>$row['id'],'description'=>$description,'amount'=>$amount,'key'=>'commission-payout-'.$row['id']]);
    }
    private function professionalId(int $t):?int{if((Auth::user()['role']??'')!=='professional')return null;$q=Database::connection()->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND user_id=:u AND active=1');$q->execute(['t'=>$t,'u'=>Auth::user()['id']]);$id=$q->fetchColumn();return $id?(int)$id:null;}
}
