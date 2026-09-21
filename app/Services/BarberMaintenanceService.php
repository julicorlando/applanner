<?php
namespace App\Services;

use App\Core\Database;

final class BarberMaintenanceService
{
    public function run(?int $tenantId=null): array
    {
        $pdo=Database::connection();$params=[];
        $sql="SELECT pcm.*,p.name professional_name,t.name tenant_name FROM professional_compensation_models pcm JOIN professionals p ON p.id=pcm.professional_id AND p.tenant_id=pcm.tenant_id JOIN tenants t ON t.id=pcm.tenant_id WHERE p.active=1 AND COALESCE(t.is_demo,0)=0 AND LOWER(TRIM(t.category)) IN('barbearia','barber','barbershop')";
        if($tenantId){$sql.=' AND pcm.tenant_id=:tenant';$params['tenant']=$tenantId;}
        $q=$pdo->prepare($sql);$q->execute($params);$rows=$q->fetchAll();$monthly=0;$daily=0;$errors=0;
        foreach($rows as $row){try{
            $tenant=(int)$row['tenant_id'];if(!ModuleService::has('finance',$tenant))continue;$model=(string)$row['model'];
            if(in_array($model,['chair_rent','hybrid'],true)&&(float)$row['monthly_rent']>0){$monthly+=$this->monthly($pdo,$row);}
            if($model==='daily_rent'&&(float)$row['daily_rent']>0){$daily+=$this->daily($pdo,$row);}
        }catch(\Throwable $e){$errors++;error_log('[ApPlanner Barber Cron] professional='.(int)$row['professional_id'].' '.mb_substr($e->getMessage(),0,180));}}
        return ['monthly_rent_generated'=>$monthly,'daily_rent_generated'=>$daily,'errors'=>$errors];
    }

    private function monthly(\PDO $pdo,array $row): int
    {
        $today=new \DateTimeImmutable('today');$dueDay=max(1,min(28,(int)$row['rent_due_day']));$due=new \DateTimeImmutable($today->format('Y-m-').str_pad((string)$dueDay,2,'0',STR_PAD_LEFT));if($today<$due)return 0;
        $key='barber-chair-monthly-'.(int)$row['professional_id'].'-'.$today->format('Ym');$stmt=$pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,due_at,competence_at,created_at,updated_at) VALUES(:t,'chair_rent',:p,'income',:d,:amount,'outro','pending',:key,:due,:competence,NOW(),NOW())");$stmt->execute(['t'=>$row['tenant_id'],'p'=>$row['professional_id'],'d'=>'Aluguel de cadeira — '.$row['professional_name'].' — '.$today->format('m/Y'),'amount'=>round((float)$row['monthly_rent'],2),'key'=>$key,'due'=>$due->format('Y-m-d'),'competence'=>$today->format('Y-m-01')]);return $stmt->rowCount()>0?1:0;
    }

    private function daily(\PDO $pdo,array $row): int
    {
        $date=(new \DateTimeImmutable('today'))->format('Y-m-d');$worked=$pdo->prepare("SELECT 1 FROM appointments WHERE tenant_id=:t AND professional_id=:p AND status='completed' AND DATE(starts_at)=:d LIMIT 1");$worked->execute(['t'=>$row['tenant_id'],'p'=>$row['professional_id'],'d'=>$date]);if(!$worked->fetchColumn())return 0;
        $key='barber-chair-daily-'.(int)$row['professional_id'].'-'.str_replace('-','',$date);$stmt=$pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,due_at,competence_at,created_at,updated_at) VALUES(:t,'chair_rent',:p,'income',:d,:amount,'outro','pending',:key,:due,:competence,NOW(),NOW())");$stmt->execute(['t'=>$row['tenant_id'],'p'=>$row['professional_id'],'d'=>'Diária de cadeira — '.$row['professional_name'].' — '.date('d/m/Y'),'amount'=>round((float)$row['daily_rent'],2),'key'=>$key,'due'=>$date,'competence'=>$date]);return $stmt->rowCount()>0?1:0;
    }
}
