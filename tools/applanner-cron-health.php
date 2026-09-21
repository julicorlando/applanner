<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);require $root.'/app/Core/bootstrap.php';$pdo=\App\Core\Database::connection();
$json=in_array('--json',$argv,true);$strict=in_array('--strict',$argv,true);$runKey=null;foreach($argv as $a)if(str_starts_with($a,'--run='))$runKey=substr($a,6);
$expected=[
 'worker'=>['max'=>10,'schedule'=>'*/5 * * * *'],'appointment_reminders'=>['max'=>20,'schedule'=>'*/10 * * * *'],
 'automation_dispatch'=>['max'=>20,'schedule'=>'*/10 * * * *'],'arena'=>['max'=>20,'schedule'=>'*/10 * * * *'],
 'barber'=>['max'=>20,'schedule'=>'*/10 * * * *'],'auto'=>['max'=>20,'schedule'=>'*/10 * * * *'],
 'incident_monitor'=>['max'=>20,'schedule'=>'*/10 * * * *'],'memberships'=>['max'=>1500,'schedule'=>'15 2 * * *'],
 'subscription_notifications'=>['max'=>1500,'schedule'=>'30 8 * * *'],'privacy_retention'=>['max'=>1500,'schedule'=>'20 3 * * *'],
 'backup'=>['max'=>1500,'schedule'=>'10 3 * * *'],'health_alerts'=>['max'=>20,'schedule'=>'*/10 * * * *'],'growth'=>['max'=>20,'schedule'=>'*/10 * * * *']];
if($runKey!==null){if(!isset($expected[$runKey])){fwrite(STDERR,"Cron desconhecido.\n");exit(64);}$cmd=escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/cron/run.php').' '.escapeshellarg($runKey);passthru($cmd,$code);exit($code);}
$crontab='';$crontabAvailable=false;if(function_exists('exec')){$o=[];$c=0;@exec('crontab -l 2>/dev/null',$o,$c);if($c===0){$crontab=implode("\n",$o);$crontabAvailable=true;}}
$now=time();$rows=[];$counts=['ok'=>0,'warning'=>0,'failed'=>0];
foreach($expected as $key=>$spec){$file=$root.'/cron/'.$key.'.php';$wrapper=$root.'/cron/run.php';$q=$pdo->prepare("SELECT * FROM cron_heartbeats WHERE cron_key=:k ORDER BY started_at DESC,id DESC LIMIT 1");$q->execute(['k'=>$key]);$last=$q->fetch()?:null;$age=$last?(int)floor(($now-strtotime((string)($last['finished_at']?:$last['started_at'])))/60):null;$configured=$crontabAvailable?(str_contains($crontab,'cron/run.php '.$key)||str_contains($crontab,'cron/'.$key.'.php')):null;
 $status='ok';$reasons=[];if(!is_file($file)){$status='failed';$reasons[]='arquivo ausente';}elseif(!$last){$status=$strict?'failed':'warning';$reasons[]='sem heartbeat (use o wrapper cron/run.php)';}elseif($last['status']==='running'&&$age!==null&&$age>30){$status='failed';$reasons[]='execução possivelmente travada';}elseif($last['status']==='failed'){$status='failed';$reasons[]='última execução falhou';}elseif($age!==null&&$age>$spec['max']){$status='warning';$reasons[]="atrasado {$age} min";}
 if($configured===false){$status=$strict?'failed':($status==='ok'?'warning':$status);$reasons[]='não localizado no crontab';}$counts[$status]++;$rows[]=['cron'=>$key,'status'=>$status,'schedule'=>$spec['schedule'],'configured'=>$configured,'last_run'=>$last['started_at']??null,'finished_at'=>$last['finished_at']??null,'age_minutes'=>$age,'duration_ms'=>$last['duration_ms']??null,'details'=>$last['details']??null,'reasons'=>$reasons];}
$jobs=['queued'=>(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='queued'")->fetchColumn(),'failed'=>(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='failed'")->fetchColumn(),'stale'=>(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='processing' AND locked_at<DATE_SUB(NOW(),INTERVAL 15 MINUTE)")->fetchColumn()];
$disk=@disk_free_space($root);$result=['generated_at'=>date(DATE_ATOM),'php'=>PHP_VERSION,'root'=>$root,'crontab_readable'=>$crontabAvailable,'summary'=>$counts,'jobs'=>$jobs,'disk_free_mb'=>$disk===false?null:round($disk/1048576,1),'crons'=>$rows];
if($json){echo json_encode($result,JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE)."\n";}else{echo "APPLANNER — DIAGNÓSTICO DE CRONS\n".str_repeat('=',38)."\n";foreach($rows as $r){printf("%-28s %-7s última=%-19s duração=%s\n",$r['cron'],strtoupper($r['status']),$r['last_run']??'nunca',$r['duration_ms']===null?'-':$r['duration_ms'].'ms');foreach($r['reasons'] as $reason)echo "  └─ {$reason}\n";}echo "\nFila: {$jobs['queued']} aguardando | {$jobs['failed']} falhos | {$jobs['stale']} travados\n";echo "Resumo: {$counts['ok']} OK | {$counts['warning']} ALERTA | {$counts['failed']} FALHA\n";echo "\nComando seguro de teste: php tools/applanner-cron-health.php --run=worker\n";}
exit($counts['failed']>0||$jobs['failed']>0||$jobs['stale']>0?2:($counts['warning']>0?1:0));
