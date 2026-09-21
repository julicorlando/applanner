<?php
namespace App\Controllers;
use App\Core\{Auth,Audit,Database,HttpException,View};
use App\Services\PlatformMetricsService;
final class MasterCommandController
{
 public function index():void
 {
  $this->master();$pdo=Database::connection();$metrics=PlatformMetricsService::calculate();
  $summary=['active'=>$this->count($pdo,"SELECT COUNT(*) FROM subscriptions WHERE status='active'"),'trials'=>$this->count($pdo,"SELECT COUNT(*) FROM subscriptions WHERE status='trial'"),'past_due'=>$this->count($pdo,"SELECT COUNT(*) FROM subscriptions WHERE status='past_due'"),'cancelled_30d'=>$this->count($pdo,"SELECT COUNT(*) FROM subscriptions WHERE status='cancelled' AND updated_at>=DATE_SUB(NOW(),INTERVAL 30 DAY)"),'received_month'=>(float)($metrics['received_month']??0),'mrr'=>(float)($metrics['mrr']??0),'open_incidents'=>$this->count($pdo,"SELECT COUNT(*) FROM operational_incidents WHERE status<>'resolved'"),'critical_incidents'=>$this->count($pdo,"SELECT COUNT(*) FROM operational_incidents WHERE status<>'resolved' AND severity='critical'")];
  $pending=[
   ['label'=>'Leads aguardando atendimento','count'=>$this->count($pdo,"SELECT COUNT(*) FROM commercial_leads WHERE assigned_to IS NULL AND status='new' AND do_not_contact=0"),'url'=>'/comercial/oportunidades','severity'=>'warning'],
   ['label'=>'Leads com SLA vencido','count'=>$this->count($pdo,"SELECT COUNT(*) FROM commercial_leads WHERE contact_deadline_at<NOW() AND status IN('new','in_service')"),'url'=>'/comercial/oportunidades','severity'=>'danger'],
   ['label'=>'Propostas para aprovação','count'=>$this->count($pdo,"SELECT COUNT(*) FROM commercial_proposals WHERE approval_status='pending'"),'url'=>'/master/homologacao','severity'=>'warning'],
   ['label'=>'Chamados sem responsável','count'=>$this->count($pdo,"SELECT COUNT(*) FROM support_tickets WHERE assigned_to IS NULL AND status='open'"),'url'=>'/master/support','severity'=>'danger'],
   ['label'=>'Jobs falhos','count'=>$this->count($pdo,"SELECT COUNT(*) FROM jobs WHERE status='failed'"),'url'=>'/master/incidentes','severity'=>'danger'],
   ['label'=>'Pagamentos pendentes','count'=>$this->count($pdo,"SELECT COUNT(*) FROM payments WHERE status='pending' AND created_at<DATE_SUB(NOW(),INTERVAL 1 HOUR)"),'url'=>'/master/payments','severity'=>'warning'],
   ['label'=>'Solicitações de módulos','count'=>$this->count($pdo,"SELECT COUNT(*) FROM module_requests WHERE status='pending'"),'url'=>'/master/solicitacoes-modulos','severity'=>'info'],
   ['label'=>'Backups sem restauração testada','count'=>$this->count($pdo,"SELECT COUNT(*) FROM backups b WHERE b.status='completed' AND NOT EXISTS(SELECT 1 FROM backup_verifications v WHERE v.backup_id=b.id AND v.verification_type='restore' AND v.status='passed')"),'url'=>'/master/backups','severity'=>'warning']
  ];
  $tenants=$this->rows($pdo,"SELECT t.id,t.name,t.status,p.name plan_name,s.status subscription_status,s.next_billing_at,MAX(u.last_login_at) last_login_at FROM tenants t LEFT JOIN subscriptions s ON s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=t.id) LEFT JOIN plans p ON p.id=s.plan_id LEFT JOIN users u ON u.tenant_id=t.id WHERE t.deleted_at IS NULL GROUP BY t.id,p.name,s.status,s.next_billing_at ORDER BY t.created_at DESC LIMIT 10");
  $incidents=$this->rows($pdo,"SELECT id,severity,title,details,last_seen_at FROM operational_incidents WHERE status<>'resolved' ORDER BY FIELD(severity,'critical','warning','info'),last_seen_at DESC LIMIT 6");
  $activity=$this->rows($pdo,"SELECT al.action,al.entity_type,al.entity_id,al.created_at,u.name user_name FROM audit_logs al LEFT JOIN users u ON u.id=al.user_id ORDER BY al.id DESC LIMIT 12");
  $lastHomologation=$this->row($pdo,"SELECT status,score,created_at FROM homologation_runs ORDER BY id DESC LIMIT 1");
  View::render('master/command-center',['title'=>'Central de comando','metrics'=>$metrics,'summary'=>$summary,'pending'=>$pending,'tenants'=>$tenants,'incidents'=>$incidents,'activity'=>$activity,'lastHomologation'=>$lastHomologation]);
 }
 public function search():void
 {
  $this->master();$q=trim((string)($_GET['q']??''));$results=[];if(mb_strlen($q)>=2){$pdo=Database::connection();$like='%'.$q.'%';
   $sets=[
    ['type'=>'Empresa','sql'=>"SELECT id,name title,CONCAT('Empresa · ',COALESCE(category,'')) subtitle,CONCAT('/master/tenants/',id) url FROM tenants WHERE deleted_at IS NULL AND (name LIKE :q OR public_slug LIKE :q OR public_short_code LIKE :q) LIMIT 12"],
    ['type'=>'Usuário','sql'=>"SELECT u.id,u.name title,CONCAT(u.email,' · ',COALESCE(t.name,'Plataforma')) subtitle,CONCAT('/master/users/',u.id,'/edit') url FROM users u LEFT JOIN tenants t ON t.id=u.tenant_id WHERE u.name LIKE :q OR u.email LIKE :q LIMIT 12"],
    ['type'=>'Pagamento','sql'=>"SELECT p.id,CONCAT('Pagamento #',p.id) title,CONCAT(t.name,' · R$ ',FORMAT(p.amount,2),' · ',p.status) subtitle,'/master/payments' url FROM payments p JOIN tenants t ON t.id=p.tenant_id WHERE CAST(p.id AS CHAR) LIKE :q OR p.provider_reference LIKE :q OR t.name LIKE :q LIMIT 12"],
    ['type'=>'Chamado','sql'=>"SELECT st.id,CONCAT(st.protocol,' · ',st.subject) title,CONCAT(t.name,' · ',st.status) subtitle,CONCAT('/support/',st.id) url FROM support_tickets st JOIN tenants t ON t.id=st.tenant_id WHERE st.protocol LIKE :q OR st.subject LIKE :q OR t.name LIKE :q LIMIT 12"],
    ['type'=>'Lead','sql'=>"SELECT id,name title,CONCAT(email,' · ',phone) subtitle,'/comercial/oportunidades' url FROM commercial_leads WHERE anonymized_at IS NULL AND (name LIKE :q OR email LIKE :q OR phone LIKE :q) LIMIT 12"]
   ];foreach($sets as $set){try{$s=$pdo->prepare($set['sql']);$s->execute(['q'=>$like]);foreach($s->fetchAll() as $r){$r['type']=$set['type'];$results[]=$r;}}catch(\Throwable $e){error_log('[ApPlanner Master Search] '.$set['type'].' '.$e->getMessage());}}
   Audit::log('MASTER_GLOBAL_SEARCH','settings',null,null,['query_hash'=>hash('sha256',mb_strtolower($q)),'results'=>count($results)]);
  }View::render('master/search',['title'=>'Busca global','query'=>$q,'results'=>$results]);
 }
 private function master():void{Auth::requireRole('master');}
 private function count(\PDO $pdo,string $sql):int{try{return(int)$pdo->query($sql)->fetchColumn();}catch(\Throwable){return 0;}}
 private function rows(\PDO $pdo,string $sql):array{try{return$pdo->query($sql)->fetchAll();}catch(\Throwable){return[];}}
 private function row(\PDO $pdo,string $sql):array|false{try{return$pdo->query($sql)->fetch();}catch(\Throwable){return false;}}
}
