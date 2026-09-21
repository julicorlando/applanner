<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,HttpException,TenantContext,View};
use App\Services\{ModuleService,NotificationService,SubscriptionModuleService};

final class ModuleController
{
    public function masterCatalog():void
    {
        Auth::requireRole('master');$pdo=Database::connection();
        $modules=$pdo->query("SELECT m.*,(SELECT COUNT(*) FROM plan_modules pm WHERE pm.module_id=m.id AND pm.enabled=1) plans_count,(SELECT COUNT(*) FROM tenant_module_addons ta WHERE ta.module_id=m.id AND ta.status='active') addons_count FROM modules m ORDER BY m.active DESC,m.sort_order,m.name")->fetchAll();
        View::render('master/modules',['title'=>'Catálogo de módulos','modules'=>$modules]);
    }

    public function saveModule():void
    {
        Auth::requireRole('master');CSRF::enforce();$pdo=Database::connection();$id=(int)($_POST['id']??0);$name=trim((string)($_POST['name']??''));$slug=$this->slug((string)($_POST['slug']??$name));$description=trim((string)($_POST['description']??''));$price=$this->money($_POST['addon_monthly_price']??null);if(strlen($name)<2)HttpException::abort(422,'Informe o nome do módulo.');
        if($id){$q=$pdo->prepare('UPDATE modules SET name=:n,slug=:s,description=:d,addon_monthly_price=:p,addon_sellable=:sell,sort_order=:sort,active=:active WHERE id=:id');$q->execute(['n'=>$name,'s'=>$slug,'d'=>$description?:null,'p'=>$price,'sell'=>isset($_POST['addon_sellable'])?1:0,'sort'=>(int)($_POST['sort_order']??0),'active'=>isset($_POST['active'])?1:0,'id'=>$id]);}else{$q=$pdo->prepare('INSERT INTO modules(slug,name,description,addon_monthly_price,addon_sellable,sort_order,active)VALUES(:s,:n,:d,:p,:sell,:sort,:active)');try{$q->execute(['s'=>$slug,'n'=>$name,'d'=>$description?:null,'p'=>$price,'sell'=>isset($_POST['addon_sellable'])?1:0,'sort'=>(int)($_POST['sort_order']??0),'active'=>isset($_POST['active'])?1:0]);$id=(int)$pdo->lastInsertId();}catch(\PDOException $e){if($e->getCode()==='23000')HttpException::abort(422,'Já existe um módulo com este identificador.');throw $e;}}
        Audit::log('MASTER_MODULE_SAVED','modules',$id,null,['name'=>$name,'addon_price'=>$price]);header('Location: /master/modulos');exit;
    }

    public function requests():void
    {
        Auth::requireRole('master');$pdo=Database::connection();$rows=$pdo->query("SELECT mr.*,t.name tenant_name,m.name module_name,m.slug module_slug,u.name requester_name,s.billing_cycle,s.contracted_price,s.base_contracted_price,s.addon_contracted_price FROM module_requests mr JOIN tenants t ON t.id=mr.tenant_id JOIN modules m ON m.id=mr.module_id JOIN users u ON u.id=mr.requested_by LEFT JOIN subscriptions s ON s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=mr.tenant_id) ORDER BY FIELD(mr.status,'pending','approved','awaiting_payment','payment_failed','active','rejected','cancelled'),mr.created_at DESC LIMIT 500")->fetchAll();
        View::render('master/module-requests',['title'=>'Solicitações de módulos','requests'=>$rows]);
    }

    public function approve(string $id):void
    {
        Auth::requireRole('master');CSRF::enforce();$pdo=Database::connection();$requestId=(int)$id;
        $r=$pdo->prepare("SELECT mr.*,m.name module_name FROM module_requests mr JOIN modules m ON m.id=mr.module_id WHERE mr.id=:id AND mr.status='pending'");$r->execute(['id'=>$requestId]);$row=$r->fetch();if(!$row)HttpException::abort(422,'Solicitação não está pendente.');
        $price=$this->money($_POST['monthly_price']??$row['quoted_monthly_price']);if($price===null||$price<=0)HttpException::abort(422,'Informe um valor mensal válido para o módulo.');
        $note=trim((string)($_POST['note']??''));$q=$pdo->prepare("UPDATE module_requests SET status='approved',quoted_monthly_price=:price,master_note=:note,reviewed_by=:u,reviewed_at=NOW(),updated_at=NOW() WHERE id=:id AND status='pending'");$q->execute(['price'=>$price,'note'=>$note?:null,'u'=>Auth::user()['id'],'id'=>$requestId]);if(!$q->rowCount())HttpException::abort(422,'Solicitação não está pendente.');
        NotificationService::tenantOwners((int)$row['tenant_id'],'module.request.approved','Módulo aprovado','O módulo '.$row['module_name'].' foi aprovado por R$ '.number_format($price,2,',','.').'/mês. Confirme para incorporar o valor à sua assinatura.','/billing/modulos','success');
        Audit::log('MASTER_MODULE_REQUEST_APPROVED','module_requests',$requestId,null,['price'=>$price]);header('Location: /master/solicitacoes-modulos');exit;
    }

    public function reject(string $id):void
    {
        Auth::requireRole('master');CSRF::enforce();$note=trim((string)($_POST['note']??''));if($note==='')HttpException::abort(422,'Informe o motivo da recusa.');$pdo=Database::connection();$q=$pdo->prepare("UPDATE module_requests SET status='rejected',master_note=:note,reviewed_by=:u,reviewed_at=NOW(),updated_at=NOW() WHERE id=:id AND status='pending'");$q->execute(['note'=>$note,'u'=>Auth::user()['id'],'id'=>(int)$id]);if(!$q->rowCount())HttpException::abort(422,'Solicitação não está pendente.');$r=$pdo->prepare('SELECT tenant_id FROM module_requests WHERE id=:id');$r->execute(['id'=>(int)$id]);NotificationService::tenantOwners((int)$r->fetchColumn(),'module.request.rejected','Solicitação de módulo analisada','A solicitação não foi aprovada. Consulte o motivo em Minha assinatura.','/billing/modulos','warning');Audit::log('MASTER_MODULE_REQUEST_REJECTED','module_requests',(int)$id,null,['reason'=>$note]);header('Location: /master/solicitacoes-modulos');exit;
    }

    public function tenantCatalog():void
    {
        Auth::requireLogin();if(Auth::isPlatformStaff())HttpException::abort(403,'Área exclusiva de clientes.');$t=TenantContext::id();$pdo=Database::connection();
        $q=$pdo->prepare("SELECT m.*,COALESCE(pm.enabled,0) plan_enabled,COALESCE(tm.enabled,0) tenant_enabled,mr.id request_id,mr.status request_status,mr.quoted_monthly_price,mr.master_note,ta.id addon_id,ta.status addon_status,ta.billing_mode,ta.monthly_price addon_price,ta.next_billing_at FROM modules m LEFT JOIN subscriptions s ON s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=:t) LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id LEFT JOIN tenant_modules tm ON tm.tenant_id=:t2 AND tm.module_id=m.id LEFT JOIN module_requests mr ON mr.id=(SELECT MAX(mr2.id) FROM module_requests mr2 WHERE mr2.tenant_id=:t3 AND mr2.module_id=m.id) LEFT JOIN tenant_module_addons ta ON ta.tenant_id=:t4 AND ta.module_id=m.id WHERE m.active=1 ORDER BY m.sort_order,m.name");$q->execute(['t'=>$t,'t2'=>$t,'t3'=>$t,'t4'=>$t]);
        $pricing=(new SubscriptionModuleService())->breakdown($t);
        View::render('billing/modules',['title'=>'Módulos adicionais','modules'=>$q->fetchAll(),'pricing'=>$pricing]);
    }

    public function requestModule(string $id):void
    {
        Auth::requireLogin();CSRF::enforce();$t=TenantContext::id();$moduleId=(int)$id;$pdo=Database::connection();if(ModuleService::has($this->slugById($moduleId),$t))HttpException::abort(422,'Este módulo já está disponível para sua empresa.');$q=$pdo->prepare('SELECT id,name,addon_monthly_price,addon_sellable,active FROM modules WHERE id=:id');$q->execute(['id'=>$moduleId]);$m=$q->fetch();if(!$m||!$m['active']||!$m['addon_sellable']||(float)$m['addon_monthly_price']<=0)HttpException::abort(422,'Este módulo não está disponível para contratação avulsa.');$open=$pdo->prepare("SELECT 1 FROM module_requests WHERE tenant_id=:t AND module_id=:m AND status IN('pending','approved','awaiting_payment','active') LIMIT 1");$open->execute(['t'=>$t,'m'=>$moduleId]);if($open->fetchColumn())HttpException::abort(422,'Já existe uma solicitação em andamento para este módulo.');$public=bin2hex(random_bytes(16));$pdo->prepare("INSERT INTO module_requests(public_id,tenant_id,module_id,requested_by,quoted_monthly_price,status,tenant_note,created_at,updated_at)VALUES(:public,:t,:m,:u,:price,'pending',:note,NOW(),NOW())")->execute(['public'=>$public,'t'=>$t,'m'=>$moduleId,'u'=>Auth::user()['id'],'price'=>$m['addon_monthly_price'],'note'=>trim((string)($_POST['note']??''))?:null]);$requestId=(int)$pdo->lastInsertId();NotificationService::platformStaff('module.request.new','Nova solicitação de módulo',Auth::user()['name'].' solicitou '.$m['name'].' por R$ '.number_format((float)$m['addon_monthly_price'],2,',','.').'/mês.','/master/solicitacoes-modulos','info');Audit::log('MODULE_REQUEST_CREATED','module_requests',$requestId,null,['module_id'=>$moduleId,'price'=>$m['addon_monthly_price']]);header('Location: /billing/modulos');exit;
    }

    public function checkout(string $id):void
    {
        Auth::requireRole('owner');CSRF::enforce();$t=TenantContext::id();$requestId=(int)$id;
        try{$result=(new SubscriptionModuleService())->activateApprovedRequest($requestId,$t,(int)Auth::user()['id']);}catch(\DomainException $e){HttpException::abort(422,$e->getMessage());}catch(\Throwable $e){error_log('[ApPlanner module merge] tenant='.$t.' request='.$requestId.' '.$e->getMessage());HttpException::abort(502,'Não foi possível atualizar o valor da assinatura. Nenhum módulo foi ativado.');}
        NotificationService::tenantOwners($t,'module.addon.active','Módulo incorporado à assinatura','O módulo '.$result['module_name'].' foi ativado. Novo valor da assinatura: R$ '.number_format((float)$result['new_total'],2,',','.').'.','/billing','success');
        Audit::log('MODULE_MERGED_INTO_SUBSCRIPTION','module_requests',$requestId,null,$result);header('Location: /billing/modulos');exit;
    }

    public function cancelAddon(string $id):void
    {
        Auth::requireRole('owner');CSRF::enforce();$t=TenantContext::id();$addonId=(int)$id;
        try{$result=(new SubscriptionModuleService())->cancelAddon($addonId,$t,(int)Auth::user()['id']);}catch(\DomainException $e){HttpException::abort(422,$e->getMessage());}catch(\Throwable $e){error_log('[ApPlanner module cancel] tenant='.$t.' addon='.$addonId.' '.$e->getMessage());HttpException::abort(502,'Não foi possível atualizar/cancelar a cobrança do módulo.');}
        Audit::log('MODULE_ADDON_CANCELLED','tenant_module_addons',$addonId,null,$result);header('Location: /billing/modulos');exit;
    }

    private function slugById(int $id):string{$q=Database::connection()->prepare('SELECT slug FROM modules WHERE id=:id');$q->execute(['id'=>$id]);return (string)$q->fetchColumn();}
    private function slug(string $v):string{$v=iconv('UTF-8','ASCII//TRANSLIT//IGNORE',$v)?:$v;return trim(preg_replace('/[^a-z0-9]+/','-',strtolower($v)),'-')?:'modulo';}
    private function money(mixed $v):?float{if($v===''||$v===null)return null;$n=filter_var(str_replace(',','.',(string)$v),FILTER_VALIDATE_FLOAT);return $n===false||$n<0?null:round((float)$n,2);}
}
