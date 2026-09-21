<?php
declare(strict_types=1);

$root=dirname(__DIR__);
$checks=[];
$add=function(string $n,bool $ok)use(&$checks){
    $checks[]=['name'=>$n,'ok'=>$ok];
    if(!$ok)fwrite(STDERR,"FAIL: {$n}\n");
};

$m=(string)@file_get_contents($root.'/database/migrations/043_applanner_rc1_production_readiness.sql');
$m44=(string)@file_get_contents($root.'/database/migrations/044_demo_isolation.sql');
$w=(string)@file_get_contents($root.'/cron/worker.php');
$b=(string)@file_get_contents($root.'/app/Views/billing/modules.php');
$g=(string)@file_get_contents($root.'/tools/rc1-go-live.php');
$a=(string)@file_get_contents($root.'/tools/rc1-acceptance.php');
$bs=(string)@file_get_contents($root.'/app/Services/BackupService.php');
$metrics=(string)@file_get_contents($root.'/app/Services/PlatformMetricsService.php');

foreach(['arena','barber','auto'] as $c){
    $x=(string)@file_get_contents($root.'/cron/'.$c.'.php');
    $add("cron lock {$c}",str_contains($x,"CronLock::acquire('{$c}')"));
}

$add('migration 043 skipped enum',str_contains($m,"'skipped'"));
$add('migration 043 notifications skipped',str_contains($m,"ALTER TABLE notifications")&&str_contains($m,"'cancelled','skipped'"));
$add('migration 043 jobs.last_error',str_contains($m,'last_error'));
$add('migration 044 demo isolation',str_contains($m44,'is_demo')&&str_contains($m44,'idx_tenants_demo'));

$add('worker uses CronLock',str_contains($w,"CronLock::acquire('worker')"));
$add('worker records last_error',str_contains($w,'last_error=:error'));
$add('worker recovers stale locks',str_contains($w,"locked_at<DATE_SUB(NOW(),INTERVAL 15 MINUTE)"));
$add('worker ignores demo tenants',str_contains($w,'COALESCE(is_demo,0)=0'));

$add('billing filters invalid module rows',str_contains($b,'array_filter(is_array($modules??null)?$modules:[], \'is_array\')'));
$add('billing auth user defensive',str_contains($b,'$currentRole'));

$add('cron installer exists',is_file($root.'/tools/install-rc1-crons.php'));
$add('go-live exists',is_file($root.'/tools/rc1-go-live.php'));
$add('backup restore verifier exists',is_file($root.'/tools/rc1-verify-backup.php'));

$add('backup APP_KEY config fallback',str_contains($bs,'config/app.php')&&str_contains($bs,'keyCandidates'));
$add('backup decrypt legacy compatibility',str_contains($bs,"hash('sha256',\$env,true)"));
$add('backup restore cPanel fallback',str_contains($bs,'testRestoreWithPrefixedTables')&&str_contains($bs,'sem permissão CREATE DATABASE'));

$add('go-live requires production gateway',str_contains($g,"environment='production'")&&str_contains($g,'GO COMERCIAL'));

$paidDemoAware =
    str_contains($g,"FROM payments p JOIN tenants t ON t.id=p.tenant_id")
    && str_contains($g,"COALESCE(t.is_demo,0)=0")
    && str_contains($g,"p.status='paid'");
$add('go-live requires real paid payment excluding demo',$paidDemoAware);

$providerDemoAware =
    str_contains($g,"FROM subscriptions s JOIN tenants t ON t.id=s.tenant_id")
    && str_contains($g,'provider_subscription_id');
$add('go-live provider subscription excludes demo',$providerDemoAware);

$add('go-live requires platform webhook evidence',str_contains($g,'webhook_events'));

$tenantEvidence =
    str_contains($g,'tenant_payment_transactions')
    && str_contains($g,'tenant_payment_webhook_events')
    && str_contains($g,'tenant_payment_connections')
    && str_contains($g,'COALESCE(t.is_demo,0)=0');
$add('go-live requires tenant payment evidence excluding demo',$tenantEvidence);

$add('go-live requires no demo',str_contains($g,'Sem tenants de demonstração')&&str_contains($g,'Sem billing de demonstração'));
$add('platform metrics exclude demo',str_contains($metrics,'COALESCE(t.is_demo,0)=0'));
$landing=(string)@file_get_contents($root.'/app/Views/commercial/landing.php');
$js=(string)@file_get_contents($root.'/public/assets/js/index-conversion.js');
$add('landing has no Auto demo link',!str_contains($landing,'/auto/applanner-auto-demo'));
$add('js has no Auto demo link',!str_contains($js,'/auto/applanner-auto-demo'));
$add('no demo smoke exists',is_file($root.'/tests/no_demo_smoke.php'));

$add('acceptance cannot auto-pass backup',!str_contains($a,"'backup_restore'"));

$bad=array_filter($checks,fn($c)=>!$c['ok']);
if($bad)exit(1);

echo 'rc1 regression static: OK ('.count($checks)." verificações)\n";
