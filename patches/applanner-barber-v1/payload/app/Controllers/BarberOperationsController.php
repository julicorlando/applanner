<?php
namespace App\Controllers;

use App\Core\{Auth,Authorization,CSRF,Database,TenantContext,View,Audit,HttpException};
use App\Services\{AvailabilityService,CommissionService,LoyaltyService,ModuleService,PackageService,NotificationService};

final class BarberOperationsController
{
    public function commands(): void
    {
        Authorization::require('barber.commands.view'); $t=$this->tenant(); $pdo=Database::connection(); $p=$this->professionalId($t);
        $q=$pdo->prepare("SELECT bc.*,c.name customer_name,p.name professional_name,a.starts_at,
            COALESCE((SELECT SUM(bp.amount) FROM barber_command_payments bp WHERE bp.command_id=bc.id),0) paid_amount
            FROM barber_commands bc LEFT JOIN customers c ON c.id=bc.customer_id LEFT JOIN professionals p ON p.id=bc.professional_id
            LEFT JOIN appointments a ON a.id=bc.appointment_id
            WHERE bc.tenant_id=:t AND (:p IS NULL OR bc.professional_id=:p2) ORDER BY (bc.status='open') DESC,bc.opened_at DESC LIMIT 250");
        $q->execute(['t'=>$t,'p'=>$p,'p2'=>$p]);
        $a=$pdo->prepare("SELECT a.id,a.starts_at,c.name customer_name,s.name service_name,p.name professional_name
            FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN services s ON s.id=a.service_id LEFT JOIN professionals p ON p.id=a.professional_id
            LEFT JOIN barber_commands bc ON bc.tenant_id=a.tenant_id AND bc.appointment_id=a.id
            WHERE a.tenant_id=:t AND a.status IN('confirmed','waiting','in_progress') AND bc.id IS NULL AND (:p IS NULL OR a.professional_id=:p2)
            ORDER BY a.starts_at LIMIT 150");
        $a->execute(['t'=>$t,'p'=>$p,'p2'=>$p]);
        View::render('barber/commands',['title'=>'Comandas','commands'=>$q->fetchAll(),'appointments'=>$a->fetchAll()]);
    }

    public function openCommand(): void
    {
        Authorization::require('barber.commands.manage'); CSRF::enforce(); $t=$this->tenant(); $id=(int)($_POST['appointment_id']??0); if(!$id) HttpException::abort(422,'Selecione um atendimento.');
        $pdo=Database::connection(); $p=$this->professionalId($t); $pdo->beginTransaction();
        try {
            $q=$pdo->prepare("SELECT a.*,c.name customer_name,s.name service_name,COALESCE(a.service_price_snapshot,s.price) service_amount
                FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN services s ON s.id=a.service_id
                WHERE a.id=:id AND a.tenant_id=:t AND a.status NOT IN('cancelled','no_show') AND (:p IS NULL OR a.professional_id=:p2) FOR UPDATE");
            $q->execute(['id'=>$id,'t'=>$t,'p'=>$p,'p2'=>$p]); $a=$q->fetch(); if(!$a) throw new \DomainException('Atendimento não encontrado.');
            $e=$pdo->prepare('SELECT id FROM barber_commands WHERE tenant_id=:t AND appointment_id=:a LIMIT 1');$e->execute(['t'=>$t,'a'=>$id]);
            if($existing=$e->fetchColumn()){ $pdo->commit(); header('Location: /barber/commands/'.(int)$existing); exit; }
            $covered=PackageService::hasBalance($t,(int)$a['customer_id'],(int)$a['service_id']);
            $price=$covered?0.0:(float)$a['service_amount'];
            $pdo->prepare("INSERT INTO barber_commands(tenant_id,appointment_id,customer_id,professional_id,status,subtotal,total_amount,opened_by,opened_at,updated_at)
                VALUES(:t,:a,:c,:p,'open',:sub,:total,:u,NOW(),NOW())")->execute(['t'=>$t,'a'=>$id,'c'=>$a['customer_id'],'p'=>$a['professional_id'],'sub'=>$price,'total'=>$price,'u'=>Auth::user()['id']]);
            $cmd=(int)$pdo->lastInsertId();
            $pdo->prepare("INSERT INTO barber_command_items(command_id,tenant_id,item_type,service_id,professional_id,description,quantity,unit_price,total_amount,is_primary_service,covered_by_package,created_at)
                VALUES(:cmd,:t,'service',:s,:p,:d,1,:price,:total,1,:covered,NOW())")->execute(['cmd'=>$cmd,'t'=>$t,'s'=>$a['service_id'],'p'=>$a['professional_id'],'d'=>$a['service_name'],'price'=>$price,'total'=>$price,'covered'=>$covered?1:0]);
            $pdo->commit(); Audit::log('barber.command.opened','barber_commands',$cmd,null,['appointment_id'=>$id]);
            header('Location: /barber/commands/'.$cmd); exit;
        } catch(\Throwable $e){ if($pdo->inTransaction())$pdo->rollBack(); HttpException::abort(422,$e->getMessage()); }
    }

    public function command(string $id): void
    {
        Authorization::require('barber.commands.view'); $t=$this->tenant(); $cmdId=(int)$id; $pdo=Database::connection(); $p=$this->professionalId($t);
        $q=$pdo->prepare("SELECT bc.*,c.name customer_name,c.phone customer_phone,p.name professional_name,a.starts_at,a.status appointment_status
            FROM barber_commands bc LEFT JOIN customers c ON c.id=bc.customer_id LEFT JOIN professionals p ON p.id=bc.professional_id LEFT JOIN appointments a ON a.id=bc.appointment_id
            WHERE bc.id=:id AND bc.tenant_id=:t AND (:p IS NULL OR bc.professional_id=:p2)");$q->execute(['id'=>$cmdId,'t'=>$t,'p'=>$p,'p2'=>$p]);$command=$q->fetch(); if(!$command)HttpException::abort(404,'Comanda não encontrada.');
        $q=$pdo->prepare('SELECT i.*,p.name professional_name FROM barber_command_items i LEFT JOIN professionals p ON p.id=i.professional_id WHERE i.command_id=:c AND i.tenant_id=:t ORDER BY i.id');$q->execute(['c'=>$cmdId,'t'=>$t]);$items=$q->fetchAll();
        $q=$pdo->prepare('SELECT * FROM barber_command_payments WHERE command_id=:c AND tenant_id=:t ORDER BY received_at');$q->execute(['c'=>$cmdId,'t'=>$t]);$payments=$q->fetchAll();
        $s=$pdo->prepare('SELECT id,name,price FROM services WHERE tenant_id=:t AND active=1 ORDER BY name');$s->execute(['t'=>$t]);
        $pr=$pdo->prepare('SELECT id,name,sale_price,stock,commission_type,commission_value FROM products WHERE tenant_id=:t AND active=1 ORDER BY name');$pr->execute(['t'=>$t]);
        $pf=$pdo->prepare('SELECT id,name FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY name');$pf->execute(['t'=>$t]);
        View::render('barber/command',['title'=>'Comanda #'.$cmdId,'command'=>$command,'items'=>$items,'payments'=>$payments,'services'=>$s->fetchAll(),'products'=>$pr->fetchAll(),'professionals'=>$pf->fetchAll()]);
    }

    public function addItem(string $id): void
    {
        Authorization::require('barber.commands.manage'); CSRF::enforce(); $t=$this->tenant(); $cmd=(int)$id; $pdo=Database::connection(); $command=$this->openCommandRow($pdo,$t,$cmd);
        $type=(string)($_POST['item_type']??''); $qty=$this->number($_POST['quantity']??1,0.001); $discount=$this->money($_POST['discount_amount']??0)??0; $professional=(int)($_POST['professional_id']??0)?:($command['professional_id']?(int)$command['professional_id']:null);$bound=$this->professionalId($t);if($bound)$professional=$bound;
        if(!$qty)HttpException::abort(422,'Quantidade inválida.'); $service=null;$product=null;$description='';$price=null;$cost=0;$commission=null;
        if($type==='service'){$sid=(int)($_POST['service_id']??0);$q=$pdo->prepare('SELECT id,name,price FROM services WHERE id=:id AND tenant_id=:t AND active=1');$q->execute(['id'=>$sid,'t'=>$t]);$service=$q->fetch();if(!$service)HttpException::abort(422,'Serviço inválido.');$description=$service['name'];$price=(float)$service['price'];}
        elseif($type==='product'){$pid=(int)($_POST['product_id']??0);$q=$pdo->prepare('SELECT * FROM products WHERE id=:id AND tenant_id=:t AND active=1');$q->execute(['id'=>$pid,'t'=>$t]);$product=$q->fetch();if(!$product)HttpException::abort(422,'Produto inválido.');$description=$product['name'];$price=(float)$product['sale_price'];$cost=(float)$product['cost_price'];$gross=$price*$qty;if($product['commission_type']==='percent')$commission=round($gross*(float)$product['commission_value']/100,2);elseif($product['commission_type']==='fixed')$commission=round((float)$product['commission_value']*$qty,2);}
        elseif($type==='manual'){$description=trim((string)($_POST['description']??''));$price=$this->money($_POST['unit_price']??null);if(strlen($description)<2||$price===null)HttpException::abort(422,'Item manual inválido.');}
        else HttpException::abort(422,'Tipo de item inválido.');
        $gross=round($price*$qty,2);if($discount<0||$discount>$gross)HttpException::abort(422,'Desconto inválido.');$total=round($gross-$discount,2);
        if($professional){$q=$pdo->prepare('SELECT 1 FROM professionals WHERE id=:p AND tenant_id=:t AND active=1');$q->execute(['p'=>$professional,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(422,'Profissional inválido.');}
        $pdo->prepare("INSERT INTO barber_command_items(command_id,tenant_id,item_type,service_id,product_id,professional_id,description,quantity,unit_price,discount_amount,total_amount,cost_snapshot,commission_amount_snapshot,created_at)
            VALUES(:c,:t,:type,:s,:prod,:prof,:d,:q,:price,:discount,:total,:cost,:commission,NOW())")->execute(['c'=>$cmd,'t'=>$t,'type'=>$type,'s'=>$service['id']??null,'prod'=>$product['id']??null,'prof'=>$professional,'d'=>$description,'q'=>$qty,'price'=>$price,'discount'=>$discount,'total'=>$total,'cost'=>$cost,'commission'=>$commission]);
        $this->recalc($pdo,$t,$cmd); Audit::log('barber.command.item_added','barber_commands',$cmd,null,['type'=>$type]); header('Location: /barber/commands/'.$cmd);exit;
    }

    public function removeItem(string $id,string $item): void
    {
        Authorization::require('barber.commands.manage');CSRF::enforce();$t=$this->tenant();$cmd=(int)$id;$itemId=(int)$item;$pdo=Database::connection();$this->openCommandRow($pdo,$t,$cmd);
        $q=$pdo->prepare('DELETE FROM barber_command_items WHERE id=:id AND command_id=:c AND tenant_id=:t AND is_primary_service=0');$q->execute(['id'=>$itemId,'c'=>$cmd,'t'=>$t]);if(!$q->rowCount())HttpException::abort(422,'O serviço principal não pode ser removido.');$this->recalc($pdo,$t,$cmd);header('Location: /barber/commands/'.$cmd);exit;
    }

    public function adjustments(string $id): void
    {
        Authorization::require('barber.commands.manage');CSRF::enforce();$t=$this->tenant();$cmd=(int)$id;$pdo=Database::connection();$this->openCommandRow($pdo,$t,$cmd);
        $discount=$this->money($_POST['discount_amount']??0)??0;$surcharge=$this->money($_POST['surcharge_amount']??0)??0;$tip=$this->money($_POST['tip_amount']??0)??0;$tipProf=(int)($_POST['tip_professional_id']??0)?:null;$bound=$this->professionalId($t);if($bound&&$tip>0)$tipProf=$bound;
        if($tip>0&&!$tipProf)HttpException::abort(422,'Selecione quem receberá a gorjeta.');if($tipProf){$q=$pdo->prepare('SELECT 1 FROM professionals WHERE id=:p AND tenant_id=:t');$q->execute(['p'=>$tipProf,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(422,'Profissional da gorjeta inválido.');}
        $pdo->prepare('UPDATE barber_commands SET discount_amount=:d,surcharge_amount=:s,tip_amount=:tip,tip_professional_id=:p,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['d'=>$discount,'s'=>$surcharge,'tip'=>$tip,'p'=>$tipProf,'id'=>$cmd,'t'=>$t]);$this->recalc($pdo,$t,$cmd);header('Location: /barber/commands/'.$cmd);exit;
    }

    public function addPayment(string $id): void
    {
        Authorization::require('barber.commands.manage');CSRF::enforce();$t=$this->tenant();$cmd=(int)$id;$pdo=Database::connection();$command=$this->openCommandRow($pdo,$t,$cmd);$amount=$this->money($_POST['amount']??null);$method=trim((string)($_POST['method']??''));
        if($amount===null||$amount<=0||!in_array($method,['pix','dinheiro','credito','debito','outro'],true))HttpException::abort(422,'Pagamento inválido.');$q=$pdo->prepare('SELECT COALESCE(SUM(amount),0) FROM barber_command_payments WHERE command_id=:c AND tenant_id=:t');$q->execute(['c'=>$cmd,'t'=>$t]);$remaining=max(0,(float)$command['total_amount']-(float)$q->fetchColumn());if($amount>$remaining+0.01)HttpException::abort(422,'O pagamento excede o saldo da comanda.');
        $pdo->prepare('INSERT INTO barber_command_payments(command_id,tenant_id,method,amount,user_id,received_at)VALUES(:c,:t,:m,:a,:u,NOW())')->execute(['c'=>$cmd,'t'=>$t,'m'=>$method,'a'=>$amount,'u'=>Auth::user()['id']]);header('Location: /barber/commands/'.$cmd);exit;
    }

    public function closeCommand(string $id): void
    {
        Authorization::require('barber.commands.manage');CSRF::enforce();$t=$this->tenant();$cmd=(int)$id;$pdo=Database::connection();$pdo->beginTransaction();
        try{
            $command=$this->openCommandRow($pdo,$t,$cmd,true);$this->recalc($pdo,$t,$cmd);$q=$pdo->prepare('SELECT * FROM barber_commands WHERE id=:id AND tenant_id=:t FOR UPDATE');$q->execute(['id'=>$cmd,'t'=>$t]);$command=$q->fetch();
            $pay=$pdo->prepare('SELECT COALESCE(SUM(amount),0) amount,COUNT(*) qty FROM barber_command_payments WHERE command_id=:c AND tenant_id=:t');$pay->execute(['c'=>$cmd,'t'=>$t]);$payments=$pay->fetch();if((float)$payments['amount']+0.01<(float)$command['total_amount'])throw new \DomainException('Ainda existe saldo pendente na comanda.');
            $items=$pdo->prepare('SELECT * FROM barber_command_items WHERE command_id=:c AND tenant_id=:t ORDER BY id FOR UPDATE');$items->execute(['c'=>$cmd,'t'=>$t]);$rows=$items->fetchAll();
            foreach($rows as $item){if($item['item_type']==='product'&&$item['product_id']){$q=$pdo->prepare('SELECT stock,minimum_stock,name,unit FROM products WHERE id=:p AND tenant_id=:t FOR UPDATE');$q->execute(['p'=>$item['product_id'],'t'=>$t]);$product=$q->fetch();if(!$product)throw new \DomainException('Produto da comanda não existe mais.');$new=(float)$product['stock']-(float)$item['quantity'];if(ModuleService::has('stock',$t)&&$new<0)throw new \DomainException('Estoque insuficiente para '.$product['name'].'.');if(ModuleService::has('stock',$t)){$pdo->prepare('UPDATE products SET stock=:s,updated_at=NOW() WHERE id=:p AND tenant_id=:t')->execute(['s'=>$new,'p'=>$item['product_id'],'t'=>$t]);$pdo->prepare("INSERT INTO product_stock_movements(tenant_id,product_id,type,quantity,balance_after,user_id,reason,created_at)VALUES(:t,:p,'command',:q,:b,:u,:r,NOW())")->execute(['t'=>$t,'p'=>$item['product_id'],'q'=>-(float)$item['quantity'],'b'=>$new,'u'=>Auth::user()['id'],'r'=>'Comanda #'.$cmd]);}}
            }
            if($command['appointment_id']){$a=$pdo->prepare('SELECT * FROM appointments WHERE id=:id AND tenant_id=:t FOR UPDATE');$a->execute(['id'=>$command['appointment_id'],'t'=>$t]);$appointment=$a->fetch();if($appointment){if($this->primaryCovered($rows))PackageService::consumeForAppointment($t,(int)$appointment['id'],(int)$appointment['customer_id'],(int)$appointment['service_id']);$pdo->prepare("UPDATE appointments SET status='completed',service_completed_at=COALESCE(service_completed_at,NOW()),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>$appointment['id'],'t'=>$t]);CommissionService::service($t,(int)$appointment['id']);}}
            foreach($rows as $item){if($item['is_primary_service'])continue;if($item['item_type']==='service')CommissionService::commandService($t,(int)$item['id']);elseif($item['item_type']==='product')CommissionService::commandProduct($t,(int)$item['id']);}
            if((float)$command['tip_amount']>0&&$command['tip_professional_id'])CommissionService::tip($t,$cmd,(int)$command['tip_professional_id'],(float)$command['tip_amount']);
            if(ModuleService::has('finance',$t)){$methods=$pdo->prepare('SELECT GROUP_CONCAT(DISTINCT method ORDER BY method) FROM barber_command_payments WHERE command_id=:c AND tenant_id=:t');$methods->execute(['c'=>$cmd,'t'=>$t]);$method=(string)($methods->fetchColumn()?:'outro');$pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,appointment_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,competence_at,paid_at,created_at,updated_at)VALUES(:t,:a,'barber_command',:sid,'income',:d,:amount,:method,'paid',:key,CURDATE(),NOW(),NOW(),NOW())")->execute(['t'=>$t,'a'=>$command['appointment_id'],'sid'=>$cmd,'d'=>'Comanda Barbearia #'.$cmd,'amount'=>$command['total_amount'],'method'=>$method,'key'=>'barber-command-'.$cmd]);}
            if($command['customer_id']){$loyaltyBase=max(0,round((float)$command['total_amount']-(float)$command['tip_amount'],2));LoyaltyService::earn($t,(int)$command['customer_id'],$loyaltyBase,'barber_command',$cmd);LoyaltyService::completeReferral($t,(int)$command['customer_id']);}
            $pdo->prepare("UPDATE barber_commands SET status='closed',closed_by=:u,closed_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['u'=>Auth::user()['id'],'id'=>$cmd,'t'=>$t]);
            if($command['appointment_id'])$pdo->prepare("UPDATE barber_queue_entries SET status='completed',completed_at=NOW(),updated_at=NOW() WHERE tenant_id=:t AND appointment_id=:a AND status='in_service'")->execute(['t'=>$t,'a'=>$command['appointment_id']]);
            $pdo->commit();Audit::log('barber.command.closed','barber_commands',$cmd,null,['total'=>$command['total_amount']]);
        }catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(422,$e->getMessage());}
        header('Location: /barber/commands/'.$cmd.'?closed=1');exit;
    }

    public function queue(): void
    {
        Authorization::require('barber.queue.view');$t=$this->tenant();$pdo=Database::connection();$p=$this->professionalId($t);$q=$pdo->prepare("SELECT q.*,s.name service_name,pp.name preferred_name,ap.name assigned_name,TIMESTAMPDIFF(MINUTE,q.joined_at,NOW()) wait_minutes FROM barber_queue_entries q JOIN services s ON s.id=q.service_id LEFT JOIN professionals pp ON pp.id=q.preferred_professional_id LEFT JOIN professionals ap ON ap.id=q.assigned_professional_id WHERE q.tenant_id=:t AND q.joined_at>=CURDATE() AND (:p IS NULL OR q.preferred_professional_id IS NULL OR q.preferred_professional_id=:p2 OR q.assigned_professional_id=:p3) ORDER BY FIELD(q.status,'waiting','called','in_service','completed','cancelled','no_show'),q.priority DESC,q.joined_at");$q->execute(['t'=>$t,'p'=>$p,'p2'=>$p,'p3'=>$p]);$s=$pdo->prepare('SELECT id,name FROM services WHERE tenant_id=:t AND active=1 ORDER BY name');$s->execute(['t'=>$t]);$pf=$pdo->prepare('SELECT id,name FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY name');$pf->execute(['t'=>$t]);$c=$pdo->prepare("SELECT id,name,phone FROM customers WHERE tenant_id=:t AND status='active' ORDER BY name LIMIT 1000");$c->execute(['t'=>$t]);View::render('barber/queue',['title'=>'Fila e encaixes','entries'=>$q->fetchAll(),'services'=>$s->fetchAll(),'professionals'=>$pf->fetchAll(),'customers'=>$c->fetchAll(),'boundProfessional'=>$p]);
    }

    public function addQueue(): void
    {
        Authorization::require('barber.queue.manage');CSRF::enforce();$t=$this->tenant();$pdo=Database::connection();$customer=(int)($_POST['customer_id']??0)?:null;$name=trim((string)($_POST['customer_name']??''));$phone=trim((string)($_POST['customer_phone']??''));$service=(int)($_POST['service_id']??0);$pref=(int)($_POST['preferred_professional_id']??0)?:null;$bound=$this->professionalId($t);if($bound)$pref=$bound;$priority=max(-10,min(10,(int)($_POST['priority']??0)));
        if($customer){$q=$pdo->prepare('SELECT name,phone FROM customers WHERE id=:c AND tenant_id=:t AND status=\'active\'');$q->execute(['c'=>$customer,'t'=>$t]);$r=$q->fetch();if(!$r)HttpException::abort(422,'Cliente inválido.');$name=$r['name'];$phone=$r['phone'];}if(strlen($name)<2||!$service)HttpException::abort(422,'Informe cliente e serviço.');$q=$pdo->prepare('SELECT 1 FROM services WHERE id=:s AND tenant_id=:t AND active=1');$q->execute(['s'=>$service,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(422,'Serviço inválido.');if($pref){$q=$pdo->prepare('SELECT 1 FROM professionals WHERE id=:p AND tenant_id=:t AND active=1');$q->execute(['p'=>$pref,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(422,'Profissional inválido.');}
        $pdo->prepare("INSERT INTO barber_queue_entries(tenant_id,customer_id,customer_name,customer_phone,service_id,preferred_professional_id,status,priority,notes,joined_at,updated_at)VALUES(:t,:c,:n,:phone,:s,:p,'waiting',:priority,:notes,NOW(),NOW())")->execute(['t'=>$t,'c'=>$customer,'n'=>$name,'phone'=>$phone?:null,'s'=>$service,'p'=>$pref,'priority'=>$priority,'notes'=>trim((string)($_POST['notes']??''))?:null]);header('Location: /barber/queue');exit;
    }

    public function callQueue(string $id): void
    {
        Authorization::require('barber.queue.manage');CSRF::enforce();$t=$this->tenant();$bound=$this->professionalId($t);$q=Database::connection()->prepare("UPDATE barber_queue_entries SET status='called',called_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t AND status='waiting' AND (:p IS NULL OR preferred_professional_id IS NULL OR preferred_professional_id=:p2 OR assigned_professional_id=:p3)");$q->execute(['id'=>(int)$id,'t'=>$t,'p'=>$bound,'p2'=>$bound,'p3'=>$bound]);if(!$q->rowCount())HttpException::abort(409,'Cliente não está mais aguardando ou pertence a outro profissional.');header('Location: /barber/queue');exit;
    }

    public function startQueue(string $id): void
    {
        Authorization::require('barber.queue.manage');CSRF::enforce();$t=$this->tenant();$qid=(int)$id;$pdo=Database::connection();$bound=$this->professionalId($t);$prof=(int)($_POST['professional_id']??0);if($bound)$prof=$bound;if(!$prof)HttpException::abort(422,'Selecione o profissional.');$pdo->beginTransaction();
        try{$q=$pdo->prepare("SELECT q.*,s.duration_minutes,s.price FROM barber_queue_entries q JOIN services s ON s.id=q.service_id AND s.tenant_id=q.tenant_id WHERE q.id=:id AND q.tenant_id=:t AND q.status IN('waiting','called') FOR UPDATE");$q->execute(['id'=>$qid,'t'=>$t]);$e=$q->fetch();if(!$e)throw new \DomainException('Encaixe não está disponível.');$availability=new AvailabilityService();if(!$availability->professionalOffers($t,$prof,(int)$e['service_id']))throw new \DomainException('Profissional não executa este serviço.');$start=new \DateTimeImmutable();$end=$start->modify('+'.(int)$e['duration_minutes'].' minutes');if(!$availability->isAvailable($t,$prof,$start,$end,null,false))throw new \DomainException('Profissional está ocupado neste momento.');$customer=$e['customer_id']?(int)$e['customer_id']:$this->createWalkInCustomer($pdo,$t,(string)$e['customer_name'],(string)$e['customer_phone']);$token=bin2hex(random_bytes(24));$pdo->prepare("INSERT INTO appointments(tenant_id,customer_id,professional_id,service_id,service_price_snapshot,starts_at,ends_at,status,source,notes,customer_manage_token_hash,customer_manage_token_encrypted,checked_in_at,service_started_at,created_by,created_at,updated_at)VALUES(:t,:c,:p,:s,:price,:st,:en,'in_progress','internal',:notes,:hash,:token,NOW(),NOW(),:u,NOW(),NOW())")->execute(['t'=>$t,'c'=>$customer,'p'=>$prof,'s'=>$e['service_id'],'price'=>$e['price'],'st'=>$start->format('Y-m-d H:i:s'),'en'=>$end->format('Y-m-d H:i:s'),'notes'=>'Encaixe / fila #'.$qid,'hash'=>hash('sha256',$token),'token'=>\App\Core\Encryption::encrypt(['token'=>$token]),'u'=>Auth::user()['id']]);$aid=(int)$pdo->lastInsertId();$pdo->prepare("UPDATE barber_queue_entries SET customer_id=:c,assigned_professional_id=:p,appointment_id=:a,status='in_service',started_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['c'=>$customer,'p'=>$prof,'a'=>$aid,'id'=>$qid,'t'=>$t]);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(409,$e->getMessage());}header('Location: /appointments');exit;
    }

    public function cancelQueue(string $id): void
    {
        Authorization::require('barber.queue.manage');CSRF::enforce();$t=$this->tenant();$bound=$this->professionalId($t);$q=Database::connection()->prepare("UPDATE barber_queue_entries SET status='cancelled',updated_at=NOW() WHERE id=:id AND tenant_id=:t AND status IN('waiting','called') AND (:p IS NULL OR preferred_professional_id IS NULL OR preferred_professional_id=:p2 OR assigned_professional_id=:p3)");$q->execute(['id'=>(int)$id,'t'=>$t,'p'=>$bound,'p2'=>$bound,'p3'=>$bound]);if(!$q->rowCount())HttpException::abort(409,'Encaixe não disponível para este profissional.');header('Location: /barber/queue');exit;
    }

    public function goals(): void
    {
        Authorization::require('barber.goals.view');$t=$this->tenant();$pdo=Database::connection();$year=max(2020,min(2100,(int)($_GET['year']??date('Y'))));$month=max(1,min(12,(int)($_GET['month']??date('n'))));$bound=$this->professionalId($t);$q=$pdo->prepare("SELECT p.id,p.name,g.revenue_target,g.services_target,g.products_target,g.ticket_target,
          (SELECT COUNT(*) FROM appointments a WHERE a.tenant_id=p.tenant_id AND a.professional_id=p.id AND a.status='completed' AND YEAR(a.starts_at)=:y1 AND MONTH(a.starts_at)=:m1) service_count,
          (SELECT COALESCE(SUM(COALESCE(a.service_price_snapshot,s.price)),0) FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.tenant_id=p.tenant_id AND a.professional_id=p.id AND a.status='completed' AND YEAR(a.starts_at)=:y2 AND MONTH(a.starts_at)=:m2) service_revenue,
          (SELECT COALESCE(SUM(sa.total),0) FROM sales sa WHERE sa.tenant_id=p.tenant_id AND sa.professional_id=p.id AND sa.status='completed' AND YEAR(sa.created_at)=:y3 AND MONTH(sa.created_at)=:m3) product_revenue
          FROM professionals p LEFT JOIN professional_goals g ON g.tenant_id=p.tenant_id AND g.professional_id=p.id AND g.year=:y4 AND g.month=:m4
          WHERE p.tenant_id=:t AND p.active=1 AND (:p IS NULL OR p.id=:p2) ORDER BY p.name");$q->execute(['y1'=>$year,'m1'=>$month,'y2'=>$year,'m2'=>$month,'y3'=>$year,'m3'=>$month,'y4'=>$year,'m4'=>$month,'t'=>$t,'p'=>$bound,'p2'=>$bound]);View::render('barber/goals',['title'=>'Metas da equipe','rows'=>$q->fetchAll(),'year'=>$year,'month'=>$month,'canManage'=>Authorization::allows('barber.goals.manage')]);
    }

    public function saveGoal(): void
    {
        Authorization::require('barber.goals.manage');CSRF::enforce();$t=$this->tenant();$p=(int)($_POST['professional_id']??0);$year=(int)($_POST['year']??date('Y'));$month=(int)($_POST['month']??date('n'));$rev=$this->money($_POST['revenue_target']??0)??0;$services=max(0,(int)($_POST['services_target']??0));$products=$this->money($_POST['products_target']??0)??0;$ticket=$this->money($_POST['ticket_target']??0)??0;if(!$p||$month<1||$month>12)HttpException::abort(422,'Meta inválida.');$db=Database::connection();$check=$db->prepare('SELECT 1 FROM professionals WHERE id=:p AND tenant_id=:t AND active=1');$check->execute(['p'=>$p,'t'=>$t]);if(!$check->fetchColumn())HttpException::abort(422,'Profissional inválido.');$q=$db->prepare("INSERT INTO professional_goals(tenant_id,professional_id,year,month,revenue_target,services_target,products_target,ticket_target,created_at,updated_at)VALUES(:t,:p,:y,:m,:r,:s,:pr,:ti,NOW(),NOW()) ON DUPLICATE KEY UPDATE revenue_target=VALUES(revenue_target),services_target=VALUES(services_target),products_target=VALUES(products_target),ticket_target=VALUES(ticket_target),updated_at=NOW()");$q->execute(['t'=>$t,'p'=>$p,'y'=>$year,'m'=>$month,'r'=>$rev,'s'=>$services,'pr'=>$products,'ti'=>$ticket]);header('Location: /barber/goals?year='.$year.'&month='.$month);exit;
    }

    public function team(string $id): void
    {
        Authorization::require('barber.compensation.manage');$t=$this->tenant();$p=(int)$id;$pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM professionals WHERE id=:p AND tenant_id=:t');$q->execute(['p'=>$p,'t'=>$t]);$prof=$q->fetch();if(!$prof)HttpException::abort(404,'Profissional não encontrado.');$s=$pdo->prepare('SELECT s.id,s.name,s.price,psc.commission_type,psc.commission_value,psc.active FROM services s LEFT JOIN professional_service_commissions psc ON psc.tenant_id=s.tenant_id AND psc.service_id=s.id AND psc.professional_id=:p WHERE s.tenant_id=:t AND s.active=1 ORDER BY s.name');$s->execute(['p'=>$p,'t'=>$t]);$c=$pdo->prepare('SELECT * FROM professional_compensation_models WHERE professional_id=:p AND tenant_id=:t');$c->execute(['p'=>$p,'t'=>$t]);View::render('barber/team',['title'=>'Modelo de trabalho','professional'=>$prof,'services'=>$s->fetchAll(),'compensation'=>$c->fetch()?:null]);
    }

    public function saveTeam(string $id): void
    {
        Authorization::require('barber.compensation.manage');CSRF::enforce();$t=$this->tenant();$p=(int)$id;$pdo=Database::connection();$q=$pdo->prepare('SELECT 1 FROM professionals WHERE id=:p AND tenant_id=:t');$q->execute(['p'=>$p,'t'=>$t]);if(!$q->fetchColumn())HttpException::abort(404,'Profissional não encontrado.');$model=(string)($_POST['model']??'commission');if(!in_array($model,['commission','chair_rent','daily_rent','hybrid'],true))$model='commission';$monthly=$this->money($_POST['monthly_rent']??0)??0;$daily=$this->money($_POST['daily_rent']??0)??0;$due=max(1,min(28,(int)($_POST['rent_due_day']??5)));$override=trim((string)($_POST['service_commission_percent']??''));$override=$override===''?null:(float)$override;if($override!==null&&($override<0||$override>100))HttpException::abort(422,'Comissão geral inválida.');$pdo->beginTransaction();try{$pdo->prepare("INSERT INTO professional_compensation_models(professional_id,tenant_id,model,monthly_rent,daily_rent,rent_due_day,service_commission_percent,notes,updated_at)VALUES(:p,:t,:m,:monthly,:daily,:due,:commission,:notes,NOW()) ON DUPLICATE KEY UPDATE model=VALUES(model),monthly_rent=VALUES(monthly_rent),daily_rent=VALUES(daily_rent),rent_due_day=VALUES(rent_due_day),service_commission_percent=VALUES(service_commission_percent),notes=VALUES(notes),updated_at=NOW()")->execute(['p'=>$p,'t'=>$t,'m'=>$model,'monthly'=>$monthly,'daily'=>$daily,'due'=>$due,'commission'=>$override,'notes'=>trim((string)($_POST['notes']??''))?:null]);$pdo->prepare('DELETE FROM professional_service_commissions WHERE tenant_id=:t AND professional_id=:p')->execute(['t'=>$t,'p'=>$p]);$ins=$pdo->prepare("INSERT INTO professional_service_commissions(tenant_id,professional_id,service_id,commission_type,commission_value,active,created_at,updated_at)VALUES(:t,:p,:s,:type,:value,1,NOW(),NOW())");$serviceCheck=$pdo->prepare('SELECT 1 FROM services WHERE id=:s AND tenant_id=:t AND active=1');foreach((array)($_POST['service_commission']??[]) as $sid=>$raw){$sid=(int)$sid;$serviceCheck->execute(['s'=>$sid,'t'=>$t]);if(!$serviceCheck->fetchColumn())throw new \DomainException('Serviço inválido na regra de comissão.');$val=trim((string)$raw);if($val==='')continue;$value=(float)str_replace(',','.',$val);$type=(string)(($_POST['service_commission_type'][$sid]??'percent'));if(!in_array($type,['percent','fixed'],true)||$value<0||($type==='percent'&&$value>100))throw new \DomainException('Comissão inválida em um dos serviços.');$ins->execute(['t'=>$t,'p'=>$p,'s'=>$sid,'type'=>$type,'value'=>$value]);}$pdo->commit();Audit::log('barber.team.compensation_saved','professionals',$p,null,['model'=>$model]);}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(422,$e->getMessage());}header('Location: /barber/team/'.$p.'?saved=1');exit;
    }

    private function tenant(): int{$t=TenantContext::id();$q=Database::connection()->prepare('SELECT category FROM tenants WHERE id=:t');$q->execute(['t'=>$t]);$c=mb_strtolower(trim((string)$q->fetchColumn()));if(!in_array($c,['barbearia','barber','barbershop'],true))HttpException::abort(404,'Recurso disponível para Barbearia.');return $t;}
    private function professionalId(int $t):?int{if((Auth::user()['role']??'')!=='professional')return null;$q=Database::connection()->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND user_id=:u AND active=1');$q->execute(['t'=>$t,'u'=>Auth::user()['id']]);$id=$q->fetchColumn();if(!$id)HttpException::abort(403,'Perfil profissional inválido.');return (int)$id;}
    private function openCommandRow(\PDO $pdo,int $t,int $id,bool $lock=false):array{$q=$pdo->prepare('SELECT * FROM barber_commands WHERE id=:id AND tenant_id=:t AND status=\'open\''.($lock?' FOR UPDATE':''));$q->execute(['id'=>$id,'t'=>$t]);$r=$q->fetch();if(!$r)HttpException::abort(409,'Comanda não está aberta.');$bound=$this->professionalId($t);if($bound&&((int)$r['professional_id']!==$bound))HttpException::abort(403,'Comanda de outro profissional.');return $r;}
    private function recalc(\PDO $pdo,int $t,int $cmd):void{$q=$pdo->prepare('SELECT COALESCE(SUM(total_amount),0) FROM barber_command_items WHERE command_id=:c AND tenant_id=:t');$q->execute(['c'=>$cmd,'t'=>$t]);$sub=round((float)$q->fetchColumn(),2);$c=$pdo->prepare('SELECT discount_amount,surcharge_amount,tip_amount FROM barber_commands WHERE id=:id AND tenant_id=:t');$c->execute(['id'=>$cmd,'t'=>$t]);$r=$c->fetch();$total=max(0,round($sub-(float)$r['discount_amount']+(float)$r['surcharge_amount']+(float)$r['tip_amount'],2));$pdo->prepare('UPDATE barber_commands SET subtotal=:s,total_amount=:total,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['s'=>$sub,'total'=>$total,'id'=>$cmd,'t'=>$t]);}
    private function primaryCovered(array $rows):bool{foreach($rows as $r)if($r['is_primary_service'])return (bool)$r['covered_by_package'];return false;}
    private function createWalkInCustomer(\PDO $pdo,int $t,string $name,string $phone):int{$q=$pdo->prepare("INSERT INTO customers(tenant_id,name,phone,consent_marketing,status,created_at,updated_at)VALUES(:t,:n,:p,0,'active',NOW(),NOW())");$q->execute(['t'=>$t,'n'=>$name,'p'=>$phone?:null]);return (int)$pdo->lastInsertId();}
    private function money(mixed $v):?float{$x=filter_var(str_replace(',','.',trim((string)$v)),FILTER_VALIDATE_FLOAT);return $x===false||$x<0?null:round((float)$x,2);}
    private function number(mixed $v,float $min):?float{$x=filter_var(str_replace(',','.',trim((string)$v)),FILTER_VALIDATE_FLOAT);return $x===false||$x<$min?null:(float)$x;}
}
