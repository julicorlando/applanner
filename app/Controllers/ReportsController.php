<?php
namespace App\Controllers;

use App\Core\{Authorization,Database,TenantContext,View};
use App\Services\ModuleService;

final class ReportsController
{
    public function index():void
    {
        Authorization::require('reports.view');$t=TenantContext::id();$pdo=Database::connection();
        $from=$this->date($_GET['from']??date('Y-m-01'));$to=$this->date($_GET['to']??date('Y-m-d'));$professionalId=filter_var($_GET['professional_id']??null,FILTER_VALIDATE_INT)?:null;
        $params=['t'=>$t,'from'=>$from.' 00:00:00','to'=>$to.' 23:59:59','p'=>$professionalId,'p2'=>$professionalId];
        $serviceSql="SELECT s.name service_name,p.name professional_name,COUNT(*) quantity,COALESCE(SUM(COALESCE(a.service_price_snapshot,s.price)),0) revenue
                     FROM appointments a JOIN services s ON s.id=a.service_id LEFT JOIN professionals p ON p.id=a.professional_id
                     WHERE a.tenant_id=:t AND a.status='completed' AND a.starts_at BETWEEN :from AND :to AND (:p IS NULL OR a.professional_id=:p2)
                     GROUP BY s.id,s.name,p.id,p.name ORDER BY revenue DESC";
        $q=$pdo->prepare($serviceSql);$q->execute($params);$services=$q->fetchAll();
        $products=[];$productsEnabled=ModuleService::has('products',$t);
        if($productsEnabled){$q=$pdo->prepare("SELECT pr.name product_name,p.name professional_name,SUM(si.quantity) quantity,SUM(si.total) revenue,SUM(si.cost_snapshot*si.quantity) cost FROM sales sa JOIN sale_items si ON si.sale_id=sa.id JOIN products pr ON pr.id=si.product_id LEFT JOIN professionals p ON p.id=sa.professional_id WHERE sa.tenant_id=:t AND sa.status='completed' AND sa.created_at BETWEEN :from AND :to AND (:p IS NULL OR sa.professional_id=:p2) GROUP BY pr.id,pr.name,p.id,p.name ORDER BY revenue DESC");$q->execute($params);$products=$q->fetchAll();}
        $q=$pdo->prepare("SELECT p.id,p.name,
          (SELECT COUNT(*) FROM appointments a WHERE a.tenant_id=:t AND a.professional_id=p.id AND a.status='completed' AND a.starts_at BETWEEN :from AND :to) service_qty,
          (SELECT COALESCE(SUM(COALESCE(a.service_price_snapshot,s.price)),0) FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.tenant_id=:t2 AND a.professional_id=p.id AND a.status='completed' AND a.starts_at BETWEEN :from2 AND :to2) service_revenue,
          (SELECT COUNT(*) FROM sales sa WHERE sa.tenant_id=:t3 AND sa.professional_id=p.id AND sa.status='completed' AND sa.created_at BETWEEN :from3 AND :to3) sale_qty,
          (SELECT COALESCE(SUM(sa.total),0) FROM sales sa WHERE sa.tenant_id=:t4 AND sa.professional_id=p.id AND sa.status='completed' AND sa.created_at BETWEEN :from4 AND :to4) product_revenue,
          (SELECT COALESCE(SUM(pc.commission_amount),0) FROM professional_commissions pc WHERE pc.tenant_id=:tc AND pc.professional_id=p.id AND pc.status<>'reversed' AND pc.created_at BETWEEN :cf AND :ct) commission_total,
          (SELECT COALESCE(SUM(pc.commission_amount),0) FROM professional_commissions pc WHERE pc.tenant_id=:tcp AND pc.professional_id=p.id AND pc.status='pending' AND pc.created_at BETWEEN :cpf AND :cpt) commission_pending,
          p.commission_percent
          FROM professionals p WHERE p.tenant_id=:tenant AND p.active=1 ORDER BY p.name");
        $q->execute(['t'=>$t,'from'=>$params['from'],'to'=>$params['to'],'t2'=>$t,'from2'=>$params['from'],'to2'=>$params['to'],'t3'=>$t,'from3'=>$params['from'],'to3'=>$params['to'],'t4'=>$t,'from4'=>$params['from'],'to4'=>$params['to'],'tc'=>$t,'cf'=>$params['from'],'ct'=>$params['to'],'tcp'=>$t,'cpf'=>$params['from'],'cpt'=>$params['to'],'tenant'=>$t]);$professionals=$q->fetchAll();
        $pf=$pdo->prepare('SELECT id,name FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY name');$pf->execute(['t'=>$t]);
        View::render('reports/index',['title'=>'Relatórios','services'=>$services,'products'=>$products,'professionals'=>$professionals,'professionalOptions'=>$pf->fetchAll(),'from'=>$from,'to'=>$to,'professionalId'=>$professionalId,'productsEnabled'=>$productsEnabled]);
    }

    private function date(mixed $value):string{$v=(string)$value;return preg_match('/^\d{4}-\d{2}-\d{2}$/',$v)?$v:date('Y-m-d');}
}
