<?php
namespace App\Services;
use App\Core\{Database,Encryption};
final class IncidentMonitorService
{
 public function scan():array
 {
  $pdo=Database::connection();$found=[];$setting=$pdo->query('SELECT * FROM platform_operation_settings WHERE id=1')->fetch()?:[];
  $checks=[
   ['job','critical','Jobs falhos',"SELECT COUNT(*) FROM jobs WHERE status='failed'",'Há %d tarefa(s) que excederam as tentativas.'],
   ['webhook','critical','Webhooks recusados',"SELECT COUNT(*) FROM webhook_events WHERE status IN('rejected','failed') AND received_at>=DATE_SUB(NOW(),INTERVAL 24 HOUR)",'Há %d webhook(s) recusado(s) ou falho(s) nas últimas 24 horas.'],
   ['email','warning','E-mails rejeitados',"SELECT COUNT(*) FROM marketing_deliveries WHERE status='failed' AND updated_at>=DATE_SUB(NOW(),INTERVAL 24 HOUR)",'Há %d e-mail(s) rejeitado(s) nas últimas 24 horas.'],
   ['whatsapp','warning','WhatsApp não entregue',"SELECT COUNT(*) FROM whatsapp_messages WHERE status='failed' AND created_at>=DATE_SUB(NOW(),INTERVAL 24 HOUR)",'Há %d mensagem(ns) WhatsApp não entregue(s).'],
   ['payment','critical','Pagamentos inconsistentes',"SELECT COUNT(*) FROM payments p LEFT JOIN invoices i ON i.id=p.reference_id AND p.purpose='invoice' WHERE (p.status='paid' AND i.id IS NOT NULL AND i.status<>'paid') OR (p.status='failed' AND i.status='paid')",'Há %d pagamento(s) com situação divergente.']
  ];
  foreach($checks as [$cat,$sev,$title,$sql,$detail]){try{$n=(int)$pdo->query($sql)->fetchColumn();if($n>0)$found[]=$this->open($pdo,$cat,$sev,$title,sprintf($detail,$n));}catch(\Throwable $e){error_log('[ApPlanner Incident Scan] '.$cat.' '.$e->getMessage());}}
  $cron=$this->setting($pdo,'cron.last_run_at');$minutes=(int)($setting['cron_stale_minutes']??15);if(!$cron||strtotime($cron)<time()-$minutes*60)$found[]=$this->open($pdo,'cron','critical','Cron atrasado','O worker não registra execução há mais de '.$minutes.' minutos.');
  $free=@disk_free_space(dirname(__DIR__,2));$min=(int)($setting['disk_min_free_mb']??1024)*1048576;if($free!==false&&$free<$min)$found[]=$this->open($pdo,'disk','critical','Espaço em disco baixo',number_format($free/1048576,0,',','.').' MB livres.');
  $log=dirname(__DIR__,2).'/error_log';
  $recentAppError=is_readable($log)&&filemtime($log)>=time()-86400&&filesize($log)>0;
  if($recentAppError)$found[]=$this->open($pdo,'application','warning','Erros recentes da aplicação','O error_log recebeu registros nas últimas 24 horas. Consulte a Central de Erros para os detalhes sanitizados.');
  else $this->resolve($pdo,'application','Erros recentes da aplicação');
  try{$pdo->query('SELECT 1');}catch(\Throwable $e){$found[]=$this->open($pdo,'database','critical','Banco indisponível',mb_substr($e->getMessage(),0,500));}
  if(!empty($setting['critical_alerts_enabled'])&&!empty($setting['critical_alert_email']))$this->queueAlerts($pdo,(string)$setting['critical_alert_email']);
  return array_values(array_filter($found));
 }
 private function open(\PDO $pdo,string $category,string $severity,string $title,string $details):int
 {
  $fingerprint=hash('sha256',$category.'|'.$title);$q=$pdo->prepare("INSERT INTO operational_incidents(fingerprint,category,severity,title,details,status,occurrence_count,first_seen_at,last_seen_at,created_at,updated_at)VALUES(:f,:c,:s,:t,:d,'open',1,NOW(),NOW(),NOW(),NOW()) ON DUPLICATE KEY UPDATE severity=VALUES(severity),details=VALUES(details),status=IF(status='resolved','open',status),occurrence_count=occurrence_count+1,last_seen_at=NOW(),updated_at=NOW(),id=LAST_INSERT_ID(id)");$q->execute(['f'=>$fingerprint,'c'=>$category,'s'=>$severity,'t'=>$title,'d'=>$details]);return (int)$pdo->lastInsertId();
 }
 private function resolve(\PDO $pdo,string $category,string $title):void
 {
  $fingerprint=hash('sha256',$category.'|'.$title);
  $q=$pdo->prepare("UPDATE operational_incidents SET status='resolved',resolved_at=COALESCE(resolved_at,NOW()),updated_at=NOW() WHERE fingerprint=:f AND status<>'resolved'");
  $q->execute(['f'=>$fingerprint]);
 }
 private function queueAlerts(\PDO $pdo,string $to):void
 {
  $rows=$pdo->query("SELECT * FROM operational_incidents WHERE status='open' AND severity='critical' AND alert_sent_at IS NULL ORDER BY id LIMIT 20")->fetchAll();foreach($rows as $r){$payload=Encryption::encrypt(['to'=>$to,'template'=>'plain','subject'=>'[ApPlanner] Incidente crítico: '.$r['title'],'message'=>$r['details'].'\n\nAcesse a Central de Incidentes do Master.']);$pdo->prepare("INSERT INTO jobs(tenant_id,type,payload_encrypted,status,attempts,available_at,created_at,updated_at)VALUES(NULL,'mail.send',:p,'queued',0,NOW(),NOW(),NOW())")->execute(['p'=>$payload]);$pdo->prepare('UPDATE operational_incidents SET alert_sent_at=NOW(),updated_at=NOW() WHERE id=:id')->execute(['id'=>$r['id']]);}
 }
 private function setting(\PDO $pdo,string $key):?string{try{$q=$pdo->prepare('SELECT setting_value FROM settings WHERE tenant_id IS NULL AND setting_key=:k ORDER BY id DESC LIMIT 1');$q->execute(['k'=>$key]);return $q->fetchColumn()?:null;}catch(\Throwable){return null;}}
}
