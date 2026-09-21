<?php
declare(strict_types=1);
require __DIR__.'/../app/Core/bootstrap.php';

use App\Core\{Database,CronLock};
use App\Services\NotificationService;

if(!CronLock::acquire('auto')){echo "Auto: já em execução.\n";exit(0);}
$pdo=Database::connection();$stats=['tenants'=>0,'estimates_expired'=>0,'crm_due'=>0];
$q=$pdo->query("SELECT id FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=0 AND status IN('trial','active') AND LOWER(TRIM(category)) IN('lava_jato','lava-jato','lava jato','detailing','estetica automotiva','estética automotiva','automotivo','automotive','auto')");
foreach($q->fetchAll() as $row){$t=(int)$row['id'];$stats['tenants']++;
    $x=$pdo->prepare("UPDATE auto_estimates SET status='expired',updated_at=NOW() WHERE tenant_id=:t AND status='sent' AND expires_at IS NOT NULL AND expires_at<=NOW()");$x->execute(['t'=>$t]);$stats['estimates_expired']+=$x->rowCount();
    $d=$pdo->prepare("SELECT e.id,e.vehicle_id,v.make,v.model,v.plate,c.name customer_name FROM auto_crm_events e JOIN customer_vehicles v ON v.id=e.vehicle_id JOIN customers c ON c.id=e.customer_id WHERE e.tenant_id=:t AND e.status='pending' AND e.due_at<=CURDATE() ORDER BY e.due_at LIMIT 50");$d->execute(['t'=>$t]);foreach($d->fetchAll() as $e){NotificationService::tenantOwners($t,'auto.crm.due','Retorno automotivo pendente',$e['customer_name'].' · '.trim(($e['make']??'').' '.$e['model'].' '.($e['plate']??'')),'/auto/crm','info');$pdo->prepare("UPDATE auto_crm_events SET status='notified',notified_at=NOW(),channel='internal',updated_at=NOW() WHERE id=:id AND tenant_id=:t AND status='pending'")->execute(['id'=>$e['id'],'t'=>$t]);$stats['crm_due']++;}
}
echo 'Auto: '.json_encode($stats,JSON_UNESCAPED_UNICODE).PHP_EOL;
