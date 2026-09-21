<?php
namespace App\Controllers;

use App\Core\{Auth,CSRF,Database,TenantContext,View,Audit,HttpException};
use App\Services\LegalDocumentService;

final class OnboardingController
{
    public function show():void
    {
        Auth::requireRole('owner');$t=TenantContext::id();$pdo=Database::connection();
        $s=$pdo->prepare('SELECT * FROM tenants WHERE id=:id');$s->execute(['id'=>$t]);$tenant=$s->fetch();
        $professional=null;$availability=[];
        if((int)($tenant['onboarding_step']??1)===6){
            $q=$pdo->prepare('SELECT * FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$q->execute(['t'=>$t]);$professional=$q->fetch();
            if($professional){$a=$pdo->prepare('SELECT * FROM professional_availability WHERE tenant_id=:t AND professional_id=:p ORDER BY weekday');$a->execute(['t'=>$t,'p'=>$professional['id']]);$availability=$a->fetchAll();}
        }
        View::render('onboarding/index',['title'=>'Primeiros passos','tenant'=>$tenant,'professional'=>$professional,'availability'=>$availability,'legal'=>LegalDocumentService::published()]);
    }

    public function save():void
    {
        Auth::requireRole('owner');CSRF::enforce();$t=TenantContext::id();$step=max(1,min(9,(int)($_POST['step']??1)));$pdo=Database::connection();$pdo->beginTransaction();
        try{
            switch($step){
                case 1:
                    $name=trim((string)($_POST['name']??''));$description=trim((string)($_POST['description']??''));if(strlen($name)<2)throw new \DomainException('Nome inválido.');
                    $pdo->prepare('UPDATE tenants SET name=:name,description=:description,onboarding_step=2,updated_at=NOW() WHERE id=:t')->execute(['name'=>$name,'description'=>$description,'t'=>$t]);break;
                case 2:
                    $color=(string)($_POST['primary_color']??'');if(!preg_match('/^#[0-9a-f]{6}$/i',$color))throw new \DomainException('Cor inválida.');
                    $pdo->prepare('UPDATE tenants SET primary_color=:color,onboarding_step=3,updated_at=NOW() WHERE id=:t')->execute(['color'=>$color,'t'=>$t]);break;
                case 3:
                    $name=trim((string)($_POST['unit_name']??''));if(!$name)throw new \DomainException('Unidade inválida.');
                    $exists=$pdo->prepare('SELECT id FROM units WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$exists->execute(['t'=>$t]);
                    if($unit=(int)$exists->fetchColumn()){$pdo->prepare('UPDATE units SET name=:name,address=:address,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['name'=>$name,'address'=>trim((string)($_POST['address']??'')),'id'=>$unit,'t'=>$t]);}
                    else{$pdo->prepare('INSERT INTO units(tenant_id,name,address,active,created_at,updated_at)VALUES(:t,:name,:address,1,NOW(),NOW())')->execute(['t'=>$t,'name'=>$name,'address'=>trim((string)($_POST['address']??''))]);}
                    $pdo->prepare('UPDATE tenants SET onboarding_step=4,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
                case 4:
                    $name=trim((string)($_POST['professional_name']??''));if(!$name)throw new \DomainException('Profissional inválido.');
                    $existing=$pdo->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$existing->execute(['t'=>$t]);$pid=(int)$existing->fetchColumn();$unit=$pdo->prepare('SELECT id FROM units WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$unit->execute(['t'=>$t]);$unitId=(int)$unit->fetchColumn()?:null;
                    if($pid){$pdo->prepare('UPDATE professionals SET name=:name,unit_id=:unit,public_slug=COALESCE(NULLIF(public_slug,\'\'),:slug),updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['name'=>$name,'unit'=>$unitId,'slug'=>$this->uniqueProfessionalSlug($pdo,$t,$name,$pid),'id'=>$pid,'t'=>$t]);}
                    else{$pdo->prepare('INSERT INTO professionals(tenant_id,unit_id,name,public_slug,active,created_at,updated_at)VALUES(:t,:unit,:name,:slug,1,NOW(),NOW())')->execute(['t'=>$t,'unit'=>$unitId,'name'=>$name,'slug'=>$this->uniqueProfessionalSlug($pdo,$t,$name)]);}
                    $pdo->prepare('UPDATE tenants SET onboarding_step=5,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
                case 5:
                    $name=trim((string)($_POST['service_name']??''));$price=filter_var(str_replace(',','.',(string)($_POST['price']??'')),FILTER_VALIDATE_FLOAT);$duration=filter_var($_POST['duration']??null,FILTER_VALIDATE_INT);
                    if(!$name||$price===false||$price<0||!$duration||$duration<5)throw new \DomainException('Serviço inválido.');
                    $existing=$pdo->prepare('SELECT id FROM services WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$existing->execute(['t'=>$t]);$sid=(int)$existing->fetchColumn();
                    if($sid)$pdo->prepare('UPDATE services SET name=:name,duration_minutes=:duration,price=:price,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['name'=>$name,'duration'=>$duration,'price'=>$price,'id'=>$sid,'t'=>$t]);
                    else{$pdo->prepare('INSERT INTO services(tenant_id,name,duration_minutes,price,active,created_at,updated_at)VALUES(:t,:name,:duration,:price,1,NOW(),NOW())')->execute(['t'=>$t,'name'=>$name,'duration'=>$duration,'price'=>$price]);$sid=(int)$pdo->lastInsertId();}
                    $prof=$pdo->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$prof->execute(['t'=>$t]);$pid=(int)$prof->fetchColumn();if($pid)$pdo->prepare('INSERT IGNORE INTO professional_services(professional_id,service_id)VALUES(:p,:s)')->execute(['p'=>$pid,'s'=>$sid]);
                    $pdo->prepare('UPDATE tenants SET onboarding_step=6,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
                case 6:
                    $prof=$pdo->prepare('SELECT id FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1');$prof->execute(['t'=>$t]);$pid=(int)$prof->fetchColumn();if(!$pid)throw new \DomainException('Cadastre um profissional antes de configurar a agenda.');
                    $enabledDays=0;
                    for($day=1;$day<=7;$day++){
                        $enabled=isset($_POST['day_'.$day]);$start=trim((string)($_POST['start_'.$day]??''));$end=trim((string)($_POST['end_'.$day]??''));
                        if($enabled){if(!preg_match('/^\d{2}:\d{2}$/',$start)||!preg_match('/^\d{2}:\d{2}$/',$end)||$start>=$end)throw new \DomainException('Revise os horários da agenda.');$enabledDays++;$pdo->prepare("INSERT INTO professional_availability(tenant_id,professional_id,weekday,start_time,end_time,active,created_at,updated_at)VALUES(:t,:p,:d,:s,:e,1,NOW(),NOW()) ON DUPLICATE KEY UPDATE start_time=VALUES(start_time),end_time=VALUES(end_time),active=1,updated_at=NOW()")->execute(['t'=>$t,'p'=>$pid,'d'=>$day,'s'=>$start.':00','e'=>$end.':00']);}
                        else{$pdo->prepare('UPDATE professional_availability SET active=0,updated_at=NOW() WHERE tenant_id=:t AND professional_id=:p AND weekday=:d')->execute(['t'=>$t,'p'=>$pid,'d'=>$day]);}
                    }
                    if($enabledDays===0)throw new \DomainException('Selecione pelo menos um dia de atendimento.');
                    $pdo->prepare('UPDATE tenants SET onboarding_step=7,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
                case 7:
                    $pdo->prepare('UPDATE tenants SET public_enabled=1,public_booking_enabled=1,onboarding_step=8,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
                case 8:
                    $pdo->prepare('UPDATE tenants SET onboarding_step=9,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
                case 9:
                    if(!isset($_POST['terms']))throw new \DomainException('Aceite os termos.');
                    LegalDocumentService::acceptCurrent((int)Auth::user()['id'],$t);$current=LegalDocumentService::current('terms');$pdo->prepare("INSERT INTO terms_acceptances(tenant_id,user_id,terms_version,ip_address,accepted_at)VALUES(:t,:u,:version,:ip,NOW())")->execute(['t'=>$t,'u'=>Auth::user()['id'],'version'=>$current['version']??'vigente','ip'=>$_SERVER['REMOTE_ADDR']??null]);
                    $pdo->prepare('UPDATE tenants SET onboarding_step=9,public_enabled=1,public_booking_enabled=1,updated_at=NOW() WHERE id=:t')->execute(['t'=>$t]);break;
            }
            $pdo->commit();Audit::log('onboarding.step','tenants',$t,null,['step'=>$step]);
        }catch(\DomainException $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(422,$e->getMessage());}
        header('Location: /onboarding');exit;
    }

    private function uniqueProfessionalSlug(\PDO $pdo,int $tenantId,string $name,?int $ignoreId=null):string
    {
        $base=$this->slug($name);$slug=$base;$i=2;
        while(true){$sql='SELECT 1 FROM professionals WHERE tenant_id=:t AND public_slug=:s'.($ignoreId?' AND id<>:id':'').' LIMIT 1';$q=$pdo->prepare($sql);$params=['t'=>$tenantId,'s'=>$slug];if($ignoreId)$params['id']=$ignoreId;$q->execute($params);if(!$q->fetchColumn())return $slug;$slug=$base.'-'.$i++;}
    }

    private function slug(string $value):string
    {
        $ascii=iconv('UTF-8','ASCII//TRANSLIT//IGNORE',$value)?:$value;$slug=trim((string)preg_replace('/[^a-z0-9]+/','-',strtolower($ascii)),'-');return $slug?:'profissional';
    }
}
