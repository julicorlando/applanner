<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,HttpException,View};
use App\Services\PlatformMetricsService;

final class PlatformFinanceController
{
    public function index():void
    {
        Auth::requireRole('master');$pdo=Database::connection();$metrics=PlatformMetricsService::calculate();
        $transactions=$pdo->query("SELECT t.*,c.name category_name,u.name created_by_name FROM platform_financial_transactions t LEFT JOIN platform_finance_categories c ON c.id=t.category_id LEFT JOIN users u ON u.id=t.created_by ORDER BY t.created_at DESC LIMIT 300")->fetchAll();
        $categories=$pdo->query("SELECT * FROM platform_finance_categories WHERE active=1 ORDER BY name")->fetchAll();
        $payments=$pdo->query("SELECT p.*,t.name tenant_name,m.name module_name,pl.name plan_name FROM payments p JOIN tenants t ON t.id=p.tenant_id LEFT JOIN subscriptions s ON s.id=p.subscription_id LEFT JOIN plans pl ON pl.id=s.plan_id LEFT JOIN module_requests mr ON p.purpose='module_addon' AND mr.id=p.reference_id LEFT JOIN modules m ON m.id=mr.module_id WHERE COALESCE(p.environment,'unknown')<>'sandbox' ORDER BY p.created_at DESC LIMIT 150")->fetchAll();
        View::render('master/finance',['title'=>'Financeiro da plataforma','metrics'=>$metrics,'transactions'=>$transactions,'categories'=>$categories,'payments'=>$payments]);
    }

    public function store():void
    {
        Auth::requireRole('master');CSRF::enforce();$type=(string)($_POST['type']??'');$description=trim((string)($_POST['description']??''));$amount=$this->money($_POST['amount']??null);$status=(string)($_POST['status']??'pending');$due=trim((string)($_POST['due_at']??''))?:null;$category=(int)($_POST['category_id']??0)?:null;if(!in_array($type,['income','expense'],true)||!in_array($status,['pending','paid'],true)||strlen($description)<2||$amount===null||$amount<=0)HttpException::abort(422,'Dados financeiros inválidos.');$q=Database::connection()->prepare("INSERT INTO platform_financial_transactions(category_id,type,description,amount,status,due_at,paid_at,notes,created_by,created_at,updated_at)VALUES(:c,:type,:d,:amount,:status,:due,IF(:status2='paid',NOW(),NULL),:notes,:u,NOW(),NOW())");$q->execute(['c'=>$category,'type'=>$type,'d'=>$description,'amount'=>$amount,'status'=>$status,'due'=>$due,'status2'=>$status,'notes'=>trim((string)($_POST['notes']??''))?:null,'u'=>Auth::user()['id']]);Audit::log('MASTER_FINANCE_TRANSACTION_CREATED','platform_financial_transactions',(int)Database::connection()->lastInsertId(),null,['type'=>$type,'amount'=>$amount]);header('Location: /master/financeiro');exit;
    }

    public function markPaid(string $id):void{Auth::requireRole('master');CSRF::enforce();Database::connection()->prepare("UPDATE platform_financial_transactions SET status='paid',paid_at=COALESCE(paid_at,NOW()),updated_at=NOW() WHERE id=:id AND status='pending'")->execute(['id'=>(int)$id]);Audit::log('MASTER_FINANCE_TRANSACTION_PAID','platform_financial_transactions',(int)$id);header('Location: /master/financeiro');exit;}
    public function cancel(string $id):void{Auth::requireRole('master');CSRF::enforce();Database::connection()->prepare("UPDATE platform_financial_transactions SET status='cancelled',updated_at=NOW() WHERE id=:id AND status<>'cancelled'")->execute(['id'=>(int)$id]);Audit::log('MASTER_FINANCE_TRANSACTION_CANCELLED','platform_financial_transactions',(int)$id);header('Location: /master/financeiro');exit;}
    public function category():void{Auth::requireRole('master');CSRF::enforce();$name=trim((string)($_POST['name']??''));$type=(string)($_POST['type']??'both');if(strlen($name)<2||!in_array($type,['income','expense','both'],true))HttpException::abort(422,'Categoria inválida.');Database::connection()->prepare("INSERT INTO platform_finance_categories(name,type,active,created_at,updated_at)VALUES(:n,:t,1,NOW(),NOW()) ON DUPLICATE KEY UPDATE type=VALUES(type),active=1,updated_at=NOW()")->execute(['n'=>$name,'t'=>$type]);header('Location: /master/financeiro');exit;}
    private function money(mixed $v):?float{if($v===''||$v===null)return null;$n=filter_var(str_replace(',','.',(string)$v),FILTER_VALIDATE_FLOAT);return $n===false?null:(float)$n;}
}
