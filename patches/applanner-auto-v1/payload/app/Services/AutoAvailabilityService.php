<?php
namespace App\Services;

use App\Core\Database;

final class AutoAvailabilityService
{
    public function service(int $tenantId,int $serviceId): ?array
    {
        $q=Database::connection()->prepare('SELECT id,name,duration_minutes,price FROM services WHERE id=:s AND tenant_id=:t AND active=1');
        $q->execute(['s'=>$serviceId,'t'=>$tenantId]);
        $row=$q->fetch(); return $row?:null;
    }

    public function settings(int $tenantId): array
    {
        $pdo=Database::connection();
        $q=$pdo->prepare('SELECT * FROM auto_settings WHERE tenant_id=:t');$q->execute(['t'=>$tenantId]);$s=$q->fetch()?:[];
        $base=(new AvailabilityService())->settings($tenantId);
        return array_merge(['slot_interval_minutes'=>30,'default_buffer_minutes'=>10,'public_enabled'=>1],$base,$s);
    }

    public function compatibleBays(int $tenantId,int $serviceId): array
    {
        $q=Database::connection()->prepare("SELECT b.* FROM auto_service_bays b
            WHERE b.tenant_id=:t AND b.active=1 AND (
              NOT EXISTS(SELECT 1 FROM auto_bay_services x WHERE x.bay_id=b.id)
              OR EXISTS(SELECT 1 FROM auto_bay_services x WHERE x.bay_id=b.id AND x.service_id=:s AND x.tenant_id=:t2)
            ) ORDER BY b.sort_order,b.name");
        $q->execute(['t'=>$tenantId,'s'=>$serviceId,'t2'=>$tenantId]);return $q->fetchAll();
    }

    public function slots(int $tenantId,int $serviceId,\DateTimeImmutable $day,?int $onlyBay=null,?int $ignoreJob=null): array
    {
        $service=$this->service($tenantId,$serviceId);if(!$service)return [];$settings=$this->settings($tenantId);
        $now=new \DateTimeImmutable();$minLead=(int)($settings['min_lead_minutes']??$settings['minimum_notice_minutes']??0);$maxDays=max(1,(int)($settings['max_advance_days']??$settings['maximum_days_ahead']??90));
        if($day < new \DateTimeImmutable('today') || $day > (new \DateTimeImmutable('today'))->modify('+'.$maxDays.' days'))return [];
        $bays=$this->compatibleBays($tenantId,$serviceId);if($onlyBay)$bays=array_values(array_filter($bays,fn($b)=>(int)$b['id']===$onlyBay));
        $weekday=(int)$day->format('N');$interval=max(5,(int)($settings['slot_interval_minutes']??30));$out=[];
        foreach($bays as $bay){
            $q=Database::connection()->prepare('SELECT start_time,end_time FROM auto_bay_hours WHERE tenant_id=:t AND bay_id=:b AND weekday=:w AND active=1 ORDER BY start_time');
            $q->execute(['t'=>$tenantId,'b'=>$bay['id'],'w'=>$weekday]);$hours=$q->fetchAll();if(!$hours)continue;
            $buffer=max((int)($settings['default_buffer_minutes']??0),(int)$bay['buffer_minutes']);
            foreach($hours as $h){
                $cursor=new \DateTimeImmutable($day->format('Y-m-d').' '.$h['start_time']);$endWindow=new \DateTimeImmutable($day->format('Y-m-d').' '.$h['end_time']);
                while($cursor < $endWindow){
                    $end=$cursor->modify('+'.(int)$service['duration_minutes'].' minutes');
                    if($end>$endWindow)break;
                    if($cursor >= $now->modify('+'.$minLead.' minutes') && $this->bayAvailable($tenantId,(int)$bay['id'],$cursor,$end,$buffer,$ignoreJob)){
                        $out[]=['bay_id'=>(int)$bay['id'],'bay_name'=>$bay['name'],'starts_at'=>$cursor->format('Y-m-d H:i:s'),'ends_at'=>$end->format('Y-m-d H:i:s'),'time'=>$cursor->format('H:i')];
                    }
                    $cursor=$cursor->modify('+'.$interval.' minutes');
                }
            }
        }
        usort($out,fn($a,$b)=>strcmp($a['starts_at'],$b['starts_at'])?:strcmp($a['bay_name'],$b['bay_name']));return $out;
    }

    public function bayAvailable(int $tenantId,int $bayId,\DateTimeImmutable $start,\DateTimeImmutable $end,int $buffer=0,?int $ignoreJob=null): bool
    {
        $s=$buffer?$start->modify('-'.$buffer.' minutes'):$start;$e=$buffer?$end->modify('+'.$buffer.' minutes'):$end;
        $q=Database::connection()->prepare("SELECT COUNT(*) FROM auto_jobs j JOIN appointments a ON a.id=j.appointment_id AND a.tenant_id=j.tenant_id
          WHERE j.tenant_id=:t AND j.bay_id=:b AND j.status NOT IN('cancelled','delivered') AND (:ignore IS NULL OR j.id<>:ignore2)
          AND a.starts_at<:e AND a.ends_at>:s");
        $q->execute(['t'=>$tenantId,'b'=>$bayId,'ignore'=>$ignoreJob,'ignore2'=>$ignoreJob,'e'=>$e->format('Y-m-d H:i:s'),'s'=>$s->format('Y-m-d H:i:s')]);
        return (int)$q->fetchColumn()===0;
    }
}
