<?php
namespace App\Controllers;

use App\Core\{Auth, Audit, Authorization, CSRF, Database, HttpException, TenantContext, View};
use App\Services\{ArenaReservationService, ModuleService};

final class SportsReservationsController
{
    private function access(string $permission = 'sports.view'): array
    {
        ModuleService::require('sports_courts');
        Authorization::require($permission);
        return [Database::connection(), (int) TenantContext::id()];
    }

    public function index(): void
    {
        [$pdo, $tenantId] = $this->access('sports.view');
        $from = $this->validDate((string)($_GET['from'] ?? '')) ?: date('Y-m-d');
        $to = $this->validDate((string)($_GET['to'] ?? '')) ?: date('Y-m-d', strtotime('+30 days'));
        if ($to < $from) [$from, $to] = [$to, $from];
        $maxTo = date('Y-m-d', strtotime($from . ' +366 days'));
        if ($to > $maxTo) $to = $maxTo;

        $q = $pdo->prepare(
            "SELECT r.*,c.name court_name,m.name modality_name,
                    f.payment_state detailed_payment_state,f.amount_paid,f.deposit_due,f.expires_at payment_expires_at,
                    tx.status provider_status,tx.pix_copy_paste
             FROM sports_reservations r
             JOIN sports_courts c ON c.id=r.court_id AND c.tenant_id=r.tenant_id
             LEFT JOIN sports_modalities m ON m.id=r.modality_id AND m.tenant_id=r.tenant_id
             LEFT JOIN sports_reservation_finance f ON f.reservation_id=r.id AND f.tenant_id=r.tenant_id
             LEFT JOIN tenant_payment_transactions tx ON tx.id=(SELECT tx2.id FROM tenant_payment_transactions tx2 WHERE tx2.tenant_id=r.tenant_id AND tx2.reference_type='reservation' AND tx2.reference_id=r.id ORDER BY tx2.id DESC LIMIT 1)
             WHERE r.tenant_id=:tenant AND r.starts_at>=:from_dt AND r.starts_at<:to_dt
             ORDER BY r.starts_at,r.id"
        );
        $q->execute(['tenant'=>$tenantId,'from_dt'=>$from.' 00:00:00','to_dt'=>date('Y-m-d H:i:s',strtotime($to.' +1 day'))]);
        $courts=$pdo->prepare('SELECT id,name,minimum_minutes,maximum_minutes FROM sports_courts WHERE tenant_id=:tenant AND active=1 ORDER BY sort_order,name');
        $courts->execute(['tenant'=>$tenantId]);
        $modalities=$pdo->prepare('SELECT m.id,m.name,cm.court_id FROM sports_modalities m JOIN sports_court_modalities cm ON cm.modality_id=m.id JOIN sports_courts c ON c.id=cm.court_id AND c.tenant_id=m.tenant_id WHERE m.tenant_id=:tenant AND m.active=1 AND c.active=1 ORDER BY m.sort_order,m.name');
        $modalities->execute(['tenant'=>$tenantId]);
        View::render('sports/reservations',[
            'title'=>'Reservas da Arena','reservations'=>$q->fetchAll()?:[],'courts'=>$courts->fetchAll()?:[],
            'modalities'=>$modalities->fetchAll()?:[],'from'=>$from,'to'=>$to,
        ]);
    }

    public function store(): void
    {
        [, $tenantId] = $this->access('sports.reservations.manage');
        CSRF::enforce();
        $courtId=(int)($_POST['court_id']??0);$modalityId=(int)($_POST['modality_id']??0);
        $duration=max(15,min(1440,(int)($_POST['duration_minutes']??60)));
        $weeks=max(1,min(52,(int)($_POST['repeat_weeks']??1)));
        try{$first=new \DateTimeImmutable((string)($_POST['starts_at']??''));}catch(\Throwable){HttpException::abort(422,'Data e horário inválidos.');}
        $customer=['name'=>trim((string)($_POST['customer_name']??'')),'phone'=>preg_replace('/\D/','',(string)($_POST['customer_phone']??'')),'email'=>trim((string)($_POST['customer_email']??''))];
        if($customer['name']===''||$courtId<=0)HttpException::abort(422,'Informe a quadra e o cliente.');
        $created=[];$group=$weeks>1?substr(hash('sha256','arena-repeat-'.$tenantId.'-'.$courtId.'-'.$first->format('c').'-'.random_bytes(8)),0,32):null;
        try{
            $service=new ArenaReservationService();
            for($i=0;$i<$weeks;$i++){
                $created[]=$service->create($tenantId,$courtId,$modalityId,$first->modify('+'.$i.' weeks'),$duration,$customer,$weeks>1?'recurring':'internal',trim((string)($_POST['notes']??''))?:null,$group,null,0,(($_POST['payment_method']??'onsite')==='pix'?'pix':'onsite'),'confirmed');
            }
        }catch(\DomainException $e){HttpException::abort(409,$e->getMessage().($created?' As ocorrências anteriores já criadas foram preservadas.':''));}
        Audit::log('ARENA_RESERVATION_CREATED','sports_reservations',$created[0]['id']??null,null,['court_id'=>$courtId,'repeat_weeks'=>$weeks,'reservation_ids'=>array_column($created,'id')]);
        header('Location: /sports/reservations?created=1');exit;
    }

    public function reschedule(string $id): void
    {
        [$pdo,$tenantId]=$this->access('sports.reservations.manage');CSRF::enforce();
        $reservationId=(int)$id;$duration=max(15,min(1440,(int)($_POST['duration_minutes']??60)));
        try{$start=new \DateTimeImmutable((string)($_POST['starts_at']??''));}catch(\Throwable){HttpException::abort(422,'Novo horário inválido.');}
        $q=$pdo->prepare("SELECT r.*,c.interval_minutes FROM sports_reservations r JOIN sports_courts c ON c.id=r.court_id AND c.tenant_id=r.tenant_id WHERE r.id=:id AND r.tenant_id=:tenant");$q->execute(['id'=>$reservationId,'tenant'=>$tenantId]);$reservation=$q->fetch();if(!$reservation)HttpException::abort(404,'Reserva não encontrada.');
        if(!in_array($reservation['status'],['pending_payment','confirmed'],true))HttpException::abort(409,'Esta reserva não pode ser remarcada.');
        if($reservation['status']==='pending_payment'){$tx=$pdo->prepare("SELECT 1 FROM tenant_payment_transactions WHERE tenant_id=:tenant AND reference_type='reservation' AND reference_id=:id AND status IN('created','pending') LIMIT 1");$tx->execute(['tenant'=>$tenantId,'id'=>$reservationId]);if($tx->fetchColumn())HttpException::abort(409,'Há uma cobrança automática pendente. Cancele a reserva/cobrança antes de alterar o horário.');}
        $service=new \App\Services\SportsAvailabilityService();$slots=$service->slots($tenantId,(int)$reservation['court_id'],(int)$reservation['modality_id'],$start->format('Y-m-d'),$duration,$reservationId);$slot=null;foreach($slots as $candidate)if($candidate['value']===$start->format('Y-m-d H:i:s')){$slot=$candidate;break;}if(!$slot)HttpException::abort(409,'O novo horário não está disponível.');
        $lockName='sports-admin-reschedule|'.$tenantId.'|'.$reservation['court_id'].'|'.$start->format('Ymd');$lock=$pdo->prepare('SELECT GET_LOCK(:lock,5)');$lock->execute(['lock'=>$lockName]);if((int)$lock->fetchColumn()!==1)HttpException::abort(409,'Outra reserva está sendo concluída nesta quadra.');
        try{$pdo->beginTransaction();$current=$pdo->prepare("SELECT r.*,c.interval_minutes FROM sports_reservations r JOIN sports_courts c ON c.id=r.court_id AND c.tenant_id=r.tenant_id WHERE r.id=:id AND r.tenant_id=:tenant FOR UPDATE");$current->execute(['id'=>$reservationId,'tenant'=>$tenantId]);$row=$current->fetch();if(!$row)throw new \DomainException('Reserva não encontrada.');$end=$start->modify('+'.$duration.' minutes');if(!$service->free($tenantId,(int)$row['court_id'],$start,$end,(int)$row['interval_minutes'],$reservationId))throw new \DomainException('O novo horário acabou de ser ocupado.');$oldStart=$row['starts_at'];$oldEnd=$row['ends_at'];$newDeposit=min((float)$row['deposit_amount'],(float)$slot['total']);$pdo->prepare("UPDATE sports_reservations SET starts_at=:starts,ends_at=:ends,duration_minutes=:duration,price_per_hour=:hour,total_amount=:total,deposit_amount=:deposit,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")->execute(['starts'=>$start->format('Y-m-d H:i:s'),'ends'=>$end->format('Y-m-d H:i:s'),'duration'=>$duration,'hour'=>$slot['price_per_hour'],'total'=>$slot['total'],'deposit'=>$newDeposit,'id'=>$reservationId,'tenant'=>$tenantId]);$pdo->prepare("UPDATE sports_reservation_finance SET gross_amount=:gross,deposit_due=:deposit,net_amount=:gross2,payment_state=CASE WHEN amount_paid>=:gross3 THEN 'paid' WHEN amount_paid>0 THEN 'partial' ELSE payment_state END,updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant")->execute(['gross'=>$slot['total'],'deposit'=>$newDeposit,'gross2'=>$slot['total'],'gross3'=>$slot['total'],'id'=>$reservationId,'tenant'=>$tenantId]);$pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,actor_user_id,created_at) VALUES(:id,'rescheduled_by_admin',:status,:status2,:notes,:user,NOW())")->execute(['id'=>$reservationId,'status'=>$row['status'],'status2'=>$row['status'],'notes'=>'De '.$oldStart.'–'.$oldEnd.' para '.$start->format('Y-m-d H:i:s').'–'.$end->format('Y-m-d H:i:s'),'user'=>(int)(Auth::user()['id']??0)?:null]);$pdo->commit();}
        catch(\DomainException $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(409,$e->getMessage());}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}finally{try{$pdo->prepare('SELECT RELEASE_LOCK(:lock)')->execute(['lock'=>$lockName]);}catch(\Throwable){}}
        Audit::log('ARENA_RESERVATION_RESCHEDULED','sports_reservations',$reservationId,null,['starts_at'=>$start->format('Y-m-d H:i:s'),'duration_minutes'=>$duration]);header('Location: /sports/reservations?rescheduled=1');exit;
    }

    public function update(string $id): void
    {
        [$pdo,$tenantId]=$this->access('sports.reservations.manage');CSRF::enforce();
        $status=(string)($_POST['status']??'');$paymentInput=(string)($_POST['payment_status']??'');
        if(!in_array($status,['pending_payment','confirmed','completed','cancelled','no_show'],true))HttpException::abort(422,'Status inválido.');
        if(!in_array($paymentInput,['not_required','pending','signal_paid','paid','refunded','cancelled'],true))HttpException::abort(422,'Pagamento inválido.');
        $before=$pdo->prepare('SELECT status,payment_status FROM sports_reservations WHERE id=:id AND tenant_id=:tenant');$before->execute(['id'=>(int)$id,'tenant'=>$tenantId]);$old=$before->fetch();if(!$old)HttpException::abort(404,'Reserva não encontrada.');
        if($paymentInput==='signal_paid' && $status==='pending_payment')$status='confirmed';
        $payment=$paymentInput==='signal_paid'?'paid':$paymentInput;
        $pdo->beginTransaction();
        try{
            $pdo->prepare("UPDATE sports_reservations SET status=:status,payment_status=:payment,confirmed_at=IF(:confirmed='confirmed' AND confirmed_at IS NULL,NOW(),confirmed_at),cancelled_at=IF(:cancelled='cancelled' AND cancelled_at IS NULL,NOW(),cancelled_at),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['status'=>$status,'payment'=>$payment,'confirmed'=>$status,'cancelled'=>$status,'id'=>(int)$id,'tenant'=>$tenantId]);
            $financeState=match($paymentInput){'signal_paid'=>'partial','paid'=>'paid','refunded'=>'refunded','cancelled'=>'cancelled','pending'=>'pending',default=>'not_required'};
            $pdo->prepare("UPDATE sports_reservation_finance
                           SET payment_state=:state,
                               amount_paid=CASE WHEN :signal=1 THEN GREATEST(amount_paid,deposit_due) WHEN :full=1 THEN GREATEST(amount_paid,gross_amount) ELSE amount_paid END,
                               amount_refunded=CASE WHEN :refund=1 THEN GREATEST(amount_refunded,amount_paid) ELSE amount_refunded END,
                               paid_at=IF(:received=1,COALESCE(paid_at,NOW()),paid_at),updated_at=NOW()
                           WHERE reservation_id=:id AND tenant_id=:tenant")
                ->execute(['state'=>$financeState,'signal'=>$paymentInput==='signal_paid'?1:0,'full'=>$paymentInput==='paid'?1:0,'refund'=>$paymentInput==='refunded'?1:0,'received'=>in_array($paymentInput,['signal_paid','paid'],true)?1:0,'id'=>(int)$id,'tenant'=>$tenantId]);
            $pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,actor_user_id,created_at) VALUES(:reservation,'admin_update',:old,:new,:notes,:user,NOW())")
                ->execute(['reservation'=>(int)$id,'old'=>$old['status'],'new'=>$status,'notes'=>'Pagamento: '.$old['payment_status'].' → '.$paymentInput,'user'=>(int)(Auth::user()['id']??0)?:null]);
            $pdo->commit();
        }catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
        Audit::log('ARENA_RESERVATION_UPDATED','sports_reservations',(int)$id,$old,['status'=>$status,'payment_status'=>$paymentInput]);
        header('Location: /sports/reservations?updated=1');exit;
    }

    private function validDate(string $date): ?string
    {
        if(!preg_match('/^\d{4}-\d{2}-\d{2}$/',$date))return null;$d=\DateTimeImmutable::createFromFormat('!Y-m-d',$date);return $d&&$d->format('Y-m-d')===$date?$date:null;
    }
}
