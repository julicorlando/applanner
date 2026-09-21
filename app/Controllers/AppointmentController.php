<?php
namespace App\Controllers;

use App\Core\{Auth,CSRF,Database,Audit,View,Authorization,TenantContext,HttpException,Encryption};
use App\Services\{BehaviorEngine,AvailabilityService,CommissionService,LoyaltyService,ModuleService,NotificationService,PackageService,PlatformSetting};

final class AppointmentController
{
    public function index():void
    {
        Authorization::require('agenda.view');$t=TenantContext::id();$p=$this->professionalId($t);$pdo=Database::connection();
        $q=$pdo->prepare("SELECT a.*,c.name customer_name,s.name service_name,p.name professional_name,v.model vehicle_model,v.plate vehicle_plate,bc.id barber_command_id,bc.status barber_command_status
            FROM appointments a JOIN customers c ON c.id=a.customer_id AND c.tenant_id=a.tenant_id JOIN services s ON s.id=a.service_id AND s.tenant_id=a.tenant_id
            LEFT JOIN professionals p ON p.id=a.professional_id LEFT JOIN customer_vehicles v ON v.id=a.vehicle_id AND v.tenant_id=a.tenant_id
            LEFT JOIN barber_commands bc ON bc.tenant_id=a.tenant_id AND bc.appointment_id=a.id
            WHERE a.tenant_id=:t AND (:p IS NULL OR a.professional_id=:p2) ORDER BY a.starts_at DESC LIMIT 400");$q->execute(['t'=>$t,'p'=>$p,'p2'=>$p]);
        View::render('appointments/index',['title'=>'Agenda','appointments'=>$q->fetchAll(),'barberMode'=>$this->barber($t)]);
    }

    public function create():void
    {
        Authorization::require('agenda.create');$t=TenantContext::id();$pdo=Database::connection();$p=$this->professionalId($t);
        $q=$pdo->prepare("SELECT id,name FROM customers WHERE tenant_id=:t AND status='active' ORDER BY name");$q->execute(['t'=>$t]);$customers=$q->fetchAll();
        $q=$pdo->prepare('SELECT id,name,duration_minutes,price FROM services WHERE tenant_id=:t AND active=1 ORDER BY name');$q->execute(['t'=>$t]);$services=$q->fetchAll();
        $q=$pdo->prepare('SELECT id,name FROM professionals WHERE tenant_id=:t AND active=1 AND (:p IS NULL OR id=:p2) ORDER BY name');$q->execute(['t'=>$t,'p'=>$p,'p2'=>$p]);$professionals=$q->fetchAll();
        $vehicles=[];if($this->automotive($t)){$q=$pdo->prepare('SELECT v.id,v.customer_id,CONCAT(v.model,IF(v.plate IS NULL OR v.plate="","",CONCAT(" • ",v.plate))) label FROM customer_vehicles v WHERE v.tenant_id=:t AND v.active=1 ORDER BY v.model');$q->execute(['t'=>$t]);$vehicles=$q->fetchAll();}
        View::render('appointments/create',['title'=>'Novo agendamento','customers'=>$customers,'services'=>$services,'professionals'=>$professionals,'vehicles'=>$vehicles]);
    }

    public function availability():void
    {
        Authorization::require('agenda.create');header('Content-Type: application/json; charset=utf-8');$t=TenantContext::id();$service=(int)($_GET['service_id']??0);$professional=(int)($_GET['professional_id']??0);$bound=$this->professionalId($t);if($bound!==null)$professional=$bound;$date=(string)($_GET['date']??'');if(!$service||!$professional||!preg_match('/^\d{4}-\d{2}-\d{2}$/',$date)){http_response_code(422);echo json_encode(['slots'=>[]]);return;}try{$day=new \DateTimeImmutable($date.' 00:00:00');}catch(\Throwable){http_response_code(422);echo json_encode(['slots'=>[]]);return;}echo json_encode(['slots'=>(new AvailabilityService())->slots($t,$service,$professional,$day,false)],JSON_UNESCAPED_UNICODE);
    }

    public function store():void
    {
        Authorization::require('agenda.create');CSRF::enforce();$t=TenantContext::id();$customer=(int)($_POST['customer_id']??0);$service=(int)($_POST['service_id']??0);$professional=(int)($_POST['professional_id']??0);$bound=$this->professionalId($t);if($bound!==null)$professional=$bound;$vehicle=(int)($_POST['vehicle_id']??0)?:null;
        try{$start=new \DateTimeImmutable((string)($_POST['starts_at']??''));}catch(\Throwable){HttpException::abort(422,'Data inválida.');}
        $pdo=Database::connection();$availability=new AvailabilityService();$sv=$availability->service($t,$service);if(!$customer||!$professional||!$sv||!$availability->professionalOffers($t,$professional,$service))HttpException::abort(422,'Cliente, serviço ou profissional inválido.');
        $q=$pdo->prepare("SELECT 1 FROM customers WHERE id=:c AND tenant_id=:t AND status='active'");$q->execute(['c'=>$customer,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(422,'Cliente inválido.');
        if($vehicle){$q=$pdo->prepare('SELECT 1 FROM customer_vehicles WHERE id=:v AND customer_id=:c AND tenant_id=:t AND active=1');$q->execute(['v'=>$vehicle,'c'=>$customer,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(422,'Veículo inválido.');}
        $end=$start->modify('+'.(int)$sv['duration_minutes'].' minutes');if(!$availability->isAvailable($t,$professional,$start,$end,null,false))HttpException::abort(409,'Horário indisponível para este profissional.');
        $token=bin2hex(random_bytes(24));$lock="agenda:$t:$professional";$lk=$pdo->prepare('SELECT GET_LOCK(:n,5)');$lk->execute(['n'=>$lock]);if((int)$lk->fetchColumn()!==1)HttpException::abort(409,'Agenda ocupada. Tente novamente.');
        try{$pdo->beginTransaction();if(!$availability->isAvailable($t,$professional,$start,$end,null,false))throw new \LogicException('Este horário acabou de ser ocupado.');$pdo->prepare("INSERT INTO appointments(tenant_id,customer_id,vehicle_id,professional_id,service_id,service_price_snapshot,starts_at,ends_at,status,source,notes,customer_manage_token_hash,customer_manage_token_encrypted,created_by,created_at,updated_at)VALUES(:t,:c,:v,:p,:s,:price,:st,:en,'confirmed','internal',:notes,:hash,:token,:u,NOW(),NOW())")->execute(['t'=>$t,'c'=>$customer,'v'=>$vehicle,'p'=>$professional,'s'=>$service,'price'=>$sv['price'],'st'=>$start->format('Y-m-d H:i:s'),'en'=>$end->format('Y-m-d H:i:s'),'notes'=>trim((string)($_POST['notes']??''))?:null,'hash'=>hash('sha256',$token),'token'=>Encryption::encrypt(['token'=>$token]),'u'=>Auth::user()['id']]);$id=(int)$pdo->lastInsertId();$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort($e instanceof \LogicException?409:422,$e->getMessage());}finally{$pdo->prepare('SELECT RELEASE_LOCK(:n)')->execute(['n'=>$lock]);}
        Audit::log('appointment.create','appointments',$id,null,['starts_at'=>$start->format('c')]);NotificationService::professional($t,$professional,'appointment.new','Novo agendamento','Você recebeu um novo atendimento em '.$start->format('d/m H:i'),'/appointments','success');header('Location: /appointments');exit;
    }

    public function updateStatus():void
    {
        Authorization::require('agenda.edit');CSRF::enforce();$t=TenantContext::id();$id=(int)($_POST['id']??0);$status=(string)($_POST['status']??'');if(!$id||!in_array($status,['pending','confirmed','waiting','in_progress','completed','cancelled','no_show'],true))HttpException::abort(422,'Status inválido.');$pdo=Database::connection();$p=$this->professionalId($t);
        $q=$pdo->prepare("SELECT a.*,COALESCE(a.service_price_snapshot,s.price) service_amount FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.id=:id AND a.tenant_id=:t AND (:p IS NULL OR a.professional_id=:p2)");$q->execute(['id'=>$id,'t'=>$t,'p'=>$p,'p2'=>$p]);$old=$q->fetch();if(!$old)HttpException::abort(404,'Agendamento não encontrado.');
        if($status==='completed'&&$this->barber($t)){$cq=$pdo->prepare("SELECT id FROM barber_commands WHERE tenant_id=:t AND appointment_id=:a AND status='open' LIMIT 1");$cq->execute(['t'=>$t,'a'=>$id]);if($open=$cq->fetchColumn())HttpException::abort(409,'Feche a comanda #'.(int)$open.' para concluir este atendimento.');}
        $extra='';if($status==='waiting')$extra=',checked_in_at=COALESCE(checked_in_at,NOW())';elseif($status==='in_progress')$extra=',checked_in_at=COALESCE(checked_in_at,NOW()),service_started_at=COALESCE(service_started_at,NOW())';elseif($status==='completed')$extra=',service_completed_at=COALESCE(service_completed_at,NOW())';
        $pdo->prepare('UPDATE appointments SET status=:s'.$extra.',updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['s'=>$status,'id'=>$id,'t'=>$t]);Audit::log('appointment.status','appointments',$id,['status'=>$old['status']],['status'=>$status]);
        if($status==='waiting'&&$old['status']!=='waiting'&&!empty($old['professional_id']))NotificationService::professional($t,(int)$old['professional_id'],'appointment.customer_arrived','Cliente aguardando','Seu cliente chegou e está aguardando atendimento.','/appointments','warning');
        if($status==='completed'&&$old['status']!=='completed'){$engine=new BehaviorEngine();$engine->recalculateCustomer($t,(int)$old['customer_id']);CommissionService::service($t,$id);LoyaltyService::earn($t,(int)$old['customer_id'],(float)$old['service_amount'],'appointment',$id);LoyaltyService::completeReferral($t,(int)$old['customer_id']);$coveredByPackage=PackageService::consumeForAppointment($t,$id,(int)$old['customer_id'],(int)$old['service_id']);if(!$coveredByPackage)$this->automaticFinance($t,$id,(float)$old['service_amount'],'Serviço concluído');}
        if($old['status']==='completed'&&$status!=='completed'){CommissionService::reverse('service',$t,$id);LoyaltyService::reverse($t,(int)$old['customer_id'],'appointment',$id);PackageService::reverseAppointment($t,$id);if(ModuleService::has('finance',$t))$pdo->prepare("UPDATE financial_transactions SET status='cancelled',updated_at=NOW() WHERE tenant_id=:t AND source_type='service' AND source_id=:sid")->execute(['t'=>$t,'sid'=>$id]);(new BehaviorEngine())->recalculateCustomer($t,(int)$old['customer_id']);}
        if($status==='cancelled'&&$old['status']!=='cancelled'){CommissionService::reverse('service',$t,$id);if($old['professional_id'])$this->notifyWaitlistMatch($t,(int)$old['service_id'],(int)$old['professional_id'],new \DateTimeImmutable($old['starts_at']));}
        header('Location: /appointments');exit;
    }

    public function reschedule(string $id):void
    {
        Authorization::require('agenda.edit');$t=TenantContext::id();$aid=(int)$id;$pdo=Database::connection();$p=$this->professionalId($t);$q=$pdo->prepare("SELECT a.*,c.name customer_name,s.name service_name FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN services s ON s.id=a.service_id WHERE a.id=:id AND a.tenant_id=:t AND (:p IS NULL OR a.professional_id=:p2)");$q->execute(['id'=>$aid,'t'=>$t,'p'=>$p,'p2'=>$p]);$a=$q->fetch();if(!$a)HttpException::abort(404,'Agendamento não encontrado.');$q=$pdo->prepare('SELECT id,name FROM professionals WHERE tenant_id=:t AND active=1 AND (:p IS NULL OR id=:p2) ORDER BY name');$q->execute(['t'=>$t,'p'=>$p,'p2'=>$p]);View::render('appointments/reschedule',['title'=>'Remarcar atendimento','appointment'=>$a,'professionals'=>$q->fetchAll()]);
    }

    public function saveReschedule(string $id):void
    {
        Authorization::require('agenda.edit');CSRF::enforce();$t=TenantContext::id();$aid=(int)$id;$pdo=Database::connection();$bound=$this->professionalId($t);$professional=(int)($_POST['professional_id']??0);if($bound!==null)$professional=$bound;try{$start=new \DateTimeImmutable((string)($_POST['starts_at']??''));}catch(\Throwable){HttpException::abort(422,'Data inválida.');}
        $q=$pdo->prepare('SELECT * FROM appointments WHERE id=:id AND tenant_id=:t');$q->execute(['id'=>$aid,'t'=>$t]);$a=$q->fetch();if(!$a)HttpException::abort(404,'Agendamento não encontrado.');$availability=new AvailabilityService();$sv=$availability->service($t,(int)$a['service_id']);if(!$sv||!$availability->professionalOffers($t,$professional,(int)$a['service_id']))HttpException::abort(422,'Profissional inválido.');$end=$start->modify('+'.(int)$sv['duration_minutes'].' minutes');if(!$availability->isAvailable($t,$professional,$start,$end,$aid,false))HttpException::abort(409,'Novo horário indisponível.');
        $pdo->beginTransaction();try{$pdo->prepare('INSERT INTO appointment_reschedule_history(tenant_id,appointment_id,old_professional_id,new_professional_id,old_starts_at,old_ends_at,new_starts_at,new_ends_at,reason,actor_type,actor_user_id,created_at)VALUES(:t,:a,:op,:np,:os,:oe,:ns,:ne,:r,\'user\',:u,NOW())')->execute(['t'=>$t,'a'=>$aid,'op'=>$a['professional_id'],'np'=>$professional,'os'=>$a['starts_at'],'oe'=>$a['ends_at'],'ns'=>$start->format('Y-m-d H:i:s'),'ne'=>$end->format('Y-m-d H:i:s'),'r'=>trim((string)($_POST['reason']??''))?:null,'u'=>Auth::user()['id']]);$pdo->prepare("UPDATE appointments SET professional_id=:p,starts_at=:s,ends_at=:e,status=IF(status='cancelled','confirmed',status),reminder_24h_sent_at=NULL,reminder_2h_sent_at=NULL,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['p'=>$professional,'s'=>$start->format('Y-m-d H:i:s'),'e'=>$end->format('Y-m-d H:i:s'),'id'=>$aid,'t'=>$t]);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('appointment.rescheduled','appointments',$aid,$a,['starts_at'=>$start->format('c'),'professional_id'=>$professional]);header('Location: /appointments');exit;
    }

    private function automaticFinance(int $t,int $appointmentId,float $amount,string $description):void
    {
        if(!ModuleService::has('finance',$t))return;$key='appointment-'.$appointmentId;$pdo=Database::connection();$pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,appointment_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,competence_at,paid_at,created_at,updated_at)VALUES(:t,:a,'service',:sid,'income',:d,:amount,'outro','paid',:key,CURDATE(),NOW(),NOW(),NOW())")->execute(['t'=>$t,'a'=>$appointmentId,'sid'=>$appointmentId,'d'=>$description,'amount'=>$amount,'key'=>$key]);
    }
    private function notifyWaitlistMatch(int $t,int $serviceId,int $professionalId,\DateTimeImmutable $slot):void
    {
        if(!ModuleService::has('waitlist',$t))return;$pdo=Database::connection();$q=$pdo->prepare("SELECT w.id,w.customer_id,c.name,c.email,c.phone,t.name tenant_name,t.public_slug,t.public_short_code,s.name service_name,p.name professional_name FROM waitlist_entries w JOIN customers c ON c.id=w.customer_id JOIN tenants t ON t.id=w.tenant_id JOIN services s ON s.id=w.service_id LEFT JOIN professionals p ON p.id=:pname WHERE w.tenant_id=:t AND w.service_id=:s AND w.status='waiting' AND (w.professional_id IS NULL OR w.professional_id=:p) AND (w.preferred_date IS NULL OR w.preferred_date=:d) AND (w.last_notified_at IS NULL OR w.last_notified_at<DATE_SUB(NOW(),INTERVAL 6 HOUR)) ORDER BY w.created_at LIMIT 5");$q->execute(['t'=>$t,'s'=>$serviceId,'p'=>$professionalId,'pname'=>$professionalId,'d'=>$slot->format('Y-m-d')]);$matches=$q->fetchAll();if(!$matches)return;NotificationService::tenantOwners($t,'waitlist.match','Horário liberado com lista de espera',count($matches).' cliente(s) compatíveis com '.$slot->format('d/m H:i'),'/waitlist','warning');$app=require dirname(__DIR__,2).'/config/app.php';foreach(array_slice($matches,0,3) as $m){$slug=$m['public_slug']?:$m['public_short_code'];$link=rtrim($app['url']??'','/').'/a/'.$slug.'/p/'.rawurlencode((string)$this->professionalSlug($t,$professionalId));$message='Olá '.$m['name'].', surgiu um horário para '.$m['service_name'].' em '.$m['tenant_name'].' no dia '.$slot->format('d/m').' às '.$slot->format('H:i').'. Veja a disponibilidade: '.$link;$sent=false;if(PlatformSetting::secret('platform.whatsapp')){$phone=preg_replace('/\D/','',(string)$m['phone']);if(preg_match('/^\d{10,15}$/',$phone)){NotificationService::queueExternal($t,'whatsapp',$phone,'Horário disponível',$message,['waitlist_id'=>$m['id']]);$sent=true;}}if(!$sent&&PlatformSetting::secret('platform.marketing_email')&&filter_var($m['email']??'',FILTER_VALIDATE_EMAIL)){NotificationService::queueExternal($t,'email',$m['email'],'Um horário ficou disponível',$message,['waitlist_id'=>$m['id']]);$sent=true;}if($sent)$pdo->prepare('UPDATE waitlist_entries SET last_notified_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['id'=>$m['id'],'t'=>$t]);}
    }
    private function professionalSlug(int $t,int $p):string{$q=Database::connection()->prepare('SELECT public_slug FROM professionals WHERE id=:p AND tenant_id=:t');$q->execute(['p'=>$p,'t'=>$t]);return (string)($q->fetchColumn()?:$p);}
    private function professionalId(int $t):?int{if((Auth::user()['role']??'')!=='professional')return null;$q=Database::connection()->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND user_id=:u AND active=1');$q->execute(['t'=>$t,'u'=>Auth::user()['id']]);$id=$q->fetchColumn();if(!$id)HttpException::abort(403,'Perfil profissional inválido.');return (int)$id;}
    private function automotive(int $t):bool{$q=Database::connection()->prepare('SELECT category FROM tenants WHERE id=:t');$q->execute(['t'=>$t]);return in_array(mb_strtolower((string)$q->fetchColumn()),['lava-jato','lava jato','detailing','automotivo','automotive'],true);}
    private function barber(int $t):bool{$q=Database::connection()->prepare('SELECT category FROM tenants WHERE id=:t');$q->execute(['t'=>$t]);return in_array(mb_strtolower(trim((string)$q->fetchColumn())),['barbearia','barber','barbershop'],true);}
}
