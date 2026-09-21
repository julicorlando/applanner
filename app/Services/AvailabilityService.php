<?php
namespace App\Services;

use App\Core\Database;

final class AvailabilityService
{
    public function settings(int $tenantId): array
    {
        $pdo=Database::connection();
        $q=$pdo->prepare('SELECT * FROM tenant_schedule_settings WHERE tenant_id=:t');$q->execute(['t'=>$tenantId]);$row=$q->fetch();
        if($row)return $row;
        $pdo->prepare('INSERT IGNORE INTO tenant_schedule_settings(tenant_id,updated_at)VALUES(:t,NOW())')->execute(['t'=>$tenantId]);
        $q->execute(['t'=>$tenantId]);return $q->fetch()?:[
            'minimum_notice_minutes'=>30,'maximum_days_ahead'=>90,'slot_interval_minutes'=>15,'buffer_minutes'=>0,
            'customer_can_cancel'=>1,'customer_can_reschedule'=>1,'cancel_notice_minutes'=>120,'reminder_24h_enabled'=>1,'reminder_2h_enabled'=>0
        ];
    }

    public function service(int $tenantId,int $serviceId): ?array
    {
        $q=Database::connection()->prepare('SELECT id,name,duration_minutes,price FROM services WHERE id=:id AND tenant_id=:t AND active=1');
        $q->execute(['id'=>$serviceId,'t'=>$tenantId]);$r=$q->fetch();return $r?:null;
    }

    public function professionalOffers(int $tenantId,int $professionalId,int $serviceId): bool
    {
        $pdo=Database::connection();$q=$pdo->prepare('SELECT 1 FROM professionals WHERE id=:p AND tenant_id=:t AND active=1');$q->execute(['p'=>$professionalId,'t'=>$tenantId]);if(!$q->fetchColumn())return false;
        $q=$pdo->prepare('SELECT COUNT(*) FROM professional_services WHERE professional_id=:p');$q->execute(['p'=>$professionalId]);if((int)$q->fetchColumn()===0)return true;
        $q=$pdo->prepare('SELECT 1 FROM professional_services ps JOIN services s ON s.id=ps.service_id WHERE ps.professional_id=:p AND ps.service_id=:s AND s.tenant_id=:t AND s.active=1');$q->execute(['p'=>$professionalId,'s'=>$serviceId,'t'=>$tenantId]);return (bool)$q->fetchColumn();
    }

    public function isAvailable(int $tenantId,int $professionalId,\DateTimeImmutable $start,\DateTimeImmutable $end,?int $excludeAppointmentId=null,bool $publicRules=true): bool
    {
        if($start->format('Y-m-d')!==$end->format('Y-m-d') || $end<=$start)return false;
        $pdo=Database::connection();$settings=$this->settings($tenantId);
        if($publicRules){
            if($start < (new \DateTimeImmutable())->modify('+'.(int)$settings['minimum_notice_minutes'].' minutes'))return false;
            if($start > (new \DateTimeImmutable())->modify('+'.(int)$settings['maximum_days_ahead'].' days'))return false;
        }
        $q=$pdo->prepare('SELECT start_time,end_time FROM professional_availability WHERE tenant_id=:t AND professional_id=:p AND weekday=:d AND active=1 LIMIT 1');
        $q->execute(['t'=>$tenantId,'p'=>$professionalId,'d'=>(int)$start->format('N')]);$a=$q->fetch();if(!$a)return false;
        $base=$start->format('Y-m-d').' ';$from=new \DateTimeImmutable($base.$a['start_time']);$to=new \DateTimeImmutable($base.$a['end_time']);if($start<$from||$end>$to)return false;
        $break=$pdo->prepare('SELECT 1 FROM professional_breaks WHERE tenant_id=:t AND professional_id=:p AND weekday=:d AND active=1 AND start_time<:end_time AND end_time>:start_time LIMIT 1');
        $break->execute(['t'=>$tenantId,'p'=>$professionalId,'d'=>(int)$start->format('N'),'start_time'=>$start->format('H:i:s'),'end_time'=>$end->format('H:i:s')]);if($break->fetchColumn())return false;
        $off=$pdo->prepare("SELECT 1 FROM professional_time_off WHERE tenant_id=:t AND professional_id=:p AND status='active' AND starts_at<:e AND ends_at>:s LIMIT 1");
        $off->execute(['t'=>$tenantId,'p'=>$professionalId,'s'=>$start->format('Y-m-d H:i:s'),'e'=>$end->format('Y-m-d H:i:s')]);if($off->fetchColumn())return false;
        $buffer=(int)$settings['buffer_minutes'];$busyStart=$buffer?$start->modify("-$buffer minutes"):$start;$busyEnd=$buffer?$end->modify("+$buffer minutes"):$end;
        $sql="SELECT 1 FROM appointments WHERE tenant_id=:t AND professional_id=:p AND status NOT IN('cancelled','no_show') AND starts_at<:e AND ends_at>:s";
        $params=['t'=>$tenantId,'p'=>$professionalId,'s'=>$busyStart->format('Y-m-d H:i:s'),'e'=>$busyEnd->format('Y-m-d H:i:s')];
        if($excludeAppointmentId){$sql.=' AND id<>:exclude';$params['exclude']=$excludeAppointmentId;}$sql.=' LIMIT 1';$q=$pdo->prepare($sql);$q->execute($params);return !$q->fetchColumn();
    }

    public function slots(int $tenantId,int $serviceId,int $professionalId,\DateTimeImmutable $day,bool $publicRules=true): array
    {
        $service=$this->service($tenantId,$serviceId);if(!$service||!$this->professionalOffers($tenantId,$professionalId,$serviceId))return [];
        $pdo=Database::connection();$q=$pdo->prepare('SELECT start_time,end_time FROM professional_availability WHERE tenant_id=:t AND professional_id=:p AND weekday=:d AND active=1 LIMIT 1');$q->execute(['t'=>$tenantId,'p'=>$professionalId,'d'=>(int)$day->format('N')]);$a=$q->fetch();if(!$a)return [];
        $settings=$this->settings($tenantId);$duration=(int)$service['duration_minutes'];$step=max(5,(int)$settings['slot_interval_minutes']);
        $cursor=new \DateTimeImmutable($day->format('Y-m-d').' '.$a['start_time']);$finish=new \DateTimeImmutable($day->format('Y-m-d').' '.$a['end_time']);$slots=[];
        while($cursor->modify("+$duration minutes")<=$finish){$end=$cursor->modify("+$duration minutes");if($this->isAvailable($tenantId,$professionalId,$cursor,$end,null,$publicRules))$slots[]=['value'=>$cursor->format('Y-m-d H:i:s'),'label'=>$cursor->format('H:i')];$cursor=$cursor->modify("+$step minutes");if(count($slots)>=96)break;}
        return $slots;
    }
}
