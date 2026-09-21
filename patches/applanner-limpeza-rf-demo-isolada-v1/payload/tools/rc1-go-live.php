<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$commercial = in_array('--commercial', $argv, true);
$external = in_array('--external', $argv, true);
require $root . '/app/Core/bootstrap.php';

use App\Core\{Database, Encryption};
use App\Services\MercadoPagoProvider;

$pdo = Database::connection();
$checks = [];
$add = function(string $area, string $name, bool $ok, string $details='', string $level='blocker') use (&$checks): void {
    $checks[] = compact('area','name','ok','details','level');
};
$tableExists = function(string $table) use ($pdo): bool {
    $db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
    $q=$pdo->prepare("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=:db AND table_name=:t");
    $q->execute(['db'=>$db,'t'=>$table]);
    return (bool)$q->fetchColumn();
};
$column = function(string $table,string $column) use ($pdo): ?array {
    try{
        $db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
        $q=$pdo->prepare("SELECT COLUMN_NAME AS Field,COLUMN_TYPE AS Type,IS_NULLABLE AS `Null`,COLUMN_DEFAULT AS `Default` FROM information_schema.columns WHERE table_schema=:db AND table_name=:t AND column_name=:c LIMIT 1");
        $q->execute(['db'=>$db,'t'=>$table,'c'=>$column]);
        $r=$q->fetch();return $r?:null;
    }catch(Throwable){return null;}
};
$count = function(string $sql) use ($pdo): int {
    try{return (int)$pdo->query($sql)->fetchColumn();}catch(Throwable){return -1;}
};
$levelForCommercial = fn(): string => $commercial ? 'blocker' : 'warning';

$app = require $root . '/config/app.php';
$add('Ambiente','PHP 8.2+',PHP_VERSION_ID>=80200,PHP_VERSION);
$add('Ambiente','Produção sem debug',($app['env']??'')==='production' && empty($app['debug']),'env='.($app['env']??'?').' debug='.(empty($app['debug'])?'off':'on'));
$add('Ambiente','Timezone da aplicação',($app['timezone']??'')==='America/Recife',(string)($app['timezone']??'N/D'),'warning');
$add('Ambiente','HTTPS configurado',str_starts_with((string)($app['url']??''),'https://'),(string)($app['url']??'N/D'));

// Migrations
$applied = $tableExists('migrations') ? ($pdo->query("SELECT migration FROM migrations")->fetchAll(PDO::FETCH_COLUMN) ?: []) : [];
foreach ([
    '037_applanner_arena_v1.sql','038_applanner_arena_v2_complete.sql',
    '039_modules_merged_subscription.sql','040_applanner_barber_v1.sql',
    '041_applanner_auto_v1.sql','042_two_factor_trusted_devices.sql',
    '043_applanner_rc1_production_readiness.sql'
] as $m) $add('Migrations',$m,in_array($m,$applied,true),in_array($m,$applied,true)?'aplicada':'ausente');

// Fila / jobs
$statusCol=$column('campaign_recipients','status');
$enum=(string)($statusCol['Type']??'');
$notifStatus=(string)(($column('notifications','status'))['Type']??'');
$add('Fila','campaign_recipients aceita skipped',str_contains($enum,"'skipped'"),$enum);
$add('Fila','notifications aceita skipped',str_contains($notifStatus,"'skipped'"),$notifStatus);
$lastErrorCol=$column('jobs','last_error');
$add('Fila','jobs.last_error disponível',$lastErrorCol!==null,$lastErrorCol?'presente':'ausente');
// Falhas históricas anteriores ao RC1 são preservadas como evidência e não bloqueiam o GO.
// O bloqueio técnico passa a considerar apenas falhas ocorridas após a migration 043.
$rc1At=null;
try{
    if($tableExists('migrations')){
        $q=$pdo->prepare("SELECT executed_at FROM migrations WHERE migration=:m ORDER BY id DESC LIMIT 1");
        $q->execute(['m'=>'043_applanner_rc1_production_readiness.sql']);
        $rc1At=$q->fetchColumn() ?: null;
    }
}catch(Throwable){$rc1At=null;}

$failedTotal=$count("SELECT COUNT(*) FROM jobs WHERE status='failed'");
$failedAfter=$failedTotal;
$failedHistorical=0;
if($rc1At){
    $q=$pdo->prepare("
        SELECT COUNT(*)
        FROM jobs
        WHERE status='failed'
          AND (tenant_id IS NULL OR tenant_id IN (SELECT id FROM tenants WHERE COALESCE(is_demo,0)=0))
          AND COALESCE(failed_at,updated_at,created_at) >= :rc1
    ");
    $q->execute(['rc1'=>$rc1At]);
    $failedAfter=(int)$q->fetchColumn();

    $q=$pdo->prepare("
        SELECT COUNT(*)
        FROM jobs
        WHERE status='failed'
          AND (tenant_id IS NULL OR tenant_id IN (SELECT id FROM tenants WHERE COALESCE(is_demo,0)=0))
          AND COALESCE(failed_at,updated_at,created_at) < :rc1
    ");
    $q->execute(['rc1'=>$rc1At]);
    $failedHistorical=(int)$q->fetchColumn();
}
$stale=$count("SELECT COUNT(*) FROM jobs WHERE status='processing' AND (tenant_id IS NULL OR tenant_id IN (SELECT id FROM tenants WHERE COALESCE(is_demo,0)=0)) AND locked_at<DATE_SUB(NOW(),INTERVAL 15 MINUTE)");

$add(
    'Fila',
    'Sem novas falhas de jobs após RC1',
    $failedAfter===0,
    $failedAfter.' falha(s) pós-RC1'.($rc1At?' | corte='.$rc1At:' | migration 043 sem timestamp')
);
$add(
    'Fila',
    'Falhas históricas preservadas',
    $failedHistorical===0,
    $failedHistorical.' falha(s) anterior(es) ao RC1; mantidas para auditoria',
    'warning'
);
$add('Fila','Sem jobs travados',$stale===0,$stale.' job(s) travado(s)');

// Crons
$cronText='';
$code=0;$out=[];@exec('crontab -l 2>&1',$out,$code);if($code===0)$cronText=implode("\n",$out);
foreach (['arena.php','barber.php','auto.php'] as $f) {
    $add('Cron',"{$f} cadastrado",str_contains($cronText,'/cron/'.$f),str_contains($cronText,'/cron/'.$f)?'presente no crontab':'não localizado');
}
foreach (['cron/worker.php','cron/arena.php','cron/barber.php','cron/auto.php'] as $f) {
    $add('Cron',"Arquivo {$f}",is_file($root.'/'.$f),is_file($root.'/'.$f)?'presente':'ausente');
}
$add('Cron','CronLock disponível',is_file($root.'/app/Core/CronLock.php'),'proteção contra sobreposição');

// Verticais
foreach ([
    'Arena'=>['sports_courts','sports_reservations','sports_commands'],
    'Barber'=>['barber_commands','barber_queue_entries','professional_service_commissions'],
    'Auto'=>['auto_service_bays','auto_jobs','auto_commands','customer_vehicles'],
    '2FA'=>['two_factor_trusted_devices'],
    'Módulos'=>['module_requests','subscription_module_adjustments','tenant_module_addons'],
] as $area=>$tables) {
    foreach ($tables as $t) $add($area,"Tabela {$t}",$tableExists($t),$tableExists($t)?'presente':'ausente');
}

// Backup real + restauração isolada já comprovada
$backupOk=false;$backupDetails='nenhum backup completed';
try{
    $b=$pdo->query("SELECT * FROM backups WHERE status='completed' ORDER BY id DESC LIMIT 1")->fetch();
    if($b){
        $path=(string)($b['path']??'');$exists=$path!==''&&is_file($path)&&is_readable($path)&&filesize($path)>100;
        $hashOk=true;if($exists&&!empty($b['checksum_sha256']))$hashOk=hash_equals((string)$b['checksum_sha256'],hash_file('sha256',$path));
        $backupOk=$exists&&$hashOk;$backupDetails='backup='.$b['id'].' arquivo='.($exists?'ok':'ausente').' checksum='.($hashOk?'ok':'divergente');
    }
}catch(Throwable $e){$backupDetails=$e->getMessage();}
$add('Backup','Backup recente íntegro',$backupOk,$backupDetails);
$restorePassed=$count("SELECT COUNT(*) FROM backup_verifications WHERE verification_type='restore' AND status='passed'")>0;
$add('Backup','Restauração isolada aprovada',$restorePassed,$restorePassed?'há verificação restore/passed':'nenhuma restauração aprovada');

// Segurança
$add('Segurança','CSRF disponível',is_file($root.'/app/Core/CSRF.php'),'app/Core/CSRF.php');
$add('Segurança','2FA confiável disponível',$tableExists('two_factor_trusted_devices') && is_file($root.'/app/Core/TrustedDevice.php'),'tabela + core');
$sessionCol=$column('users','session_version');
$add('Segurança','session_version disponível',$sessionCol!==null,$sessionCol?'presente':'ausente');
$trustedRows=$count("SELECT COUNT(*) FROM two_factor_trusted_devices WHERE expires_at>NOW()");
$add('Segurança','2FA trusted-device exercitado',$trustedRows>0,$trustedRows.' dispositivo(s) válido(s)','warning');

// Billing da plataforma (assinatura do SaaS)
$gateway=false;
try{$gateway=$pdo->query("SELECT * FROM payment_gateways WHERE provider='mercadopago' AND environment='production' ORDER BY last_tested_at DESC LIMIT 1")->fetch();}catch(Throwable){}
$gatewayValidated=is_array($gateway)&&!empty($gateway['active'])&&($gateway['last_test_status']??'')==='validated'&&!empty($gateway['access_token_encrypted']);
$add('Billing','Mercado Pago PRODUÇÃO ativo/validado',$gatewayValidated,$gateway?('ambiente='.($gateway['environment']??'?').' status='.($gateway['last_test_status']??'?').' active='.(int)($gateway['active']??0)):'produção não configurada',$levelForCommercial());
$secretOk=is_array($gateway)&&!empty($gateway['webhook_secret_encrypted']);
$add('Billing','Webhook secret de produção configurado',$secretOk,$secretOk?'configurado':'ausente',$levelForCommercial());
$providerRefs=$count("SELECT COUNT(*) FROM subscriptions s JOIN tenants t ON t.id=s.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND s.provider_subscription_id IS NOT NULL AND TRIM(s.provider_subscription_id)<>''");
$add('Billing','Assinatura com referência de provider',$providerRefs>0,$providerRefs.' assinatura(s)',$levelForCommercial());
$paidPayments=$count("SELECT COUNT(*) FROM payments p JOIN tenants t ON t.id=p.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND p.status='paid'");
$add('Billing','Pagamento end-to-end já confirmado',$paidPayments>0,$paidPayments.' pagamento(s) pago(s)',$levelForCommercial());
$webhookEvents=$count("SELECT COUNT(*) FROM webhook_events");
$add('Billing','Webhook da plataforma já processado',$webhookEvents>0,$webhookEvents.' evento(s) registrado(s)',$levelForCommercial());
$moduleApplied=$count("SELECT COUNT(*) FROM subscription_module_adjustments a JOIN tenants t ON t.id=a.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND a.status='applied'");
$add('Billing','Módulo incorporado já exercitado',$moduleApplied>0,$moduleApplied.' ajuste(s) aplicado(s)','warning');

// Billing dos estabelecimentos (Arena/Auto/Barber, quando recebem do cliente final)
$tenantConnections=$count("SELECT COUNT(*) FROM tenant_payment_connections c JOIN tenants t ON t.id=c.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND c.provider='mercadopago' AND c.status='connected'");
$add('Pagamentos do estabelecimento','Mercado Pago conectado em ao menos um tenant',$tenantConnections>0,$tenantConnections.' conexão(ões)',$levelForCommercial());
$tenantPaid=$count("SELECT COUNT(*) FROM tenant_payment_transactions x JOIN tenants t ON t.id=x.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND x.status='paid'");
$add('Pagamentos do estabelecimento','Pagamento de cliente final já conciliado',$tenantPaid>0,$tenantPaid.' transação(ões) paga(s)',$levelForCommercial());
$tenantWebhook=$count("SELECT COUNT(*) FROM tenant_payment_webhook_events w JOIN tenants t ON t.id=w.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND w.signature_valid=1 AND w.status='processed'");
$add('Pagamentos do estabelecimento','Webhook de tenant validado/processado',$tenantWebhook>0,$tenantWebhook.' evento(s)',$levelForCommercial());

// Conectividade externa (não cobra nada)
$externalOk=false;$externalDetails=$external?'não executado':'use --external';
if($external&&$gatewayValidated){
    try{
        $token=(string)(Encryption::decrypt((string)$gateway['access_token_encrypted'])['value']??'');
        $me=(new MercadoPagoProvider($token))->testConnection();
        $externalOk=!empty($me['id']);$externalDetails=$externalOk?'API de produção respondeu /users/me':'resposta sem id';
    }catch(Throwable $e){$externalDetails=mb_substr($e->getMessage(),0,180);}
}
$add('Billing','Conectividade externa Mercado Pago produção',$externalOk,$externalDetails,$levelForCommercial());

$tenantExternalOk=false;$tenantExternalDetails=$external?'nenhuma conexão testada':'use --external';
if($external && $tenantConnections>0){
    try{
        $rows=$pdo->query("SELECT c.id,c.tenant_id,c.environment,c.credentials_encrypted FROM tenant_payment_connections c JOIN tenants t ON t.id=c.tenant_id WHERE COALESCE(t.is_demo,0)=0 AND c.provider='mercadopago' AND c.status='connected' ORDER BY (c.environment='production') DESC,c.id LIMIT 5")->fetchAll()?:[];
        $tested=0;$errors=[];
        foreach($rows as $row){
            try{
                $cred=Encryption::decrypt((string)$row['credentials_encrypted']);
                $me=(new MercadoPagoProvider((string)($cred['access_token']??'')))->testConnection();
                if(empty($me['id']))throw new RuntimeException('resposta sem id');
                $tested++;
            }catch(Throwable $e){$errors[]='conn#'.$row['id'].': '.mb_substr($e->getMessage(),0,90);}
        }
        $tenantExternalOk=$tested>0 && !$errors;
        $tenantExternalDetails=$tested.' conexão(ões) testada(s)'.($errors?' | '.implode('; ',$errors):'');
    }catch(Throwable $e){$tenantExternalDetails=mb_substr($e->getMessage(),0,180);}
}
$add('Pagamentos do estabelecimento','Conectividade externa de tenant',$tenantExternalOk,$tenantExternalDetails,$levelForCommercial());

// Isolamento da demonstração
$demoColumn=$column('tenants','is_demo');
$add('Demo','Flag is_demo disponível',$demoColumn!==null,$demoColumn?'presente':'ausente');
$demoTenants=$demoColumn?$count("SELECT COUNT(*) FROM tenants WHERE is_demo=1 AND deleted_at IS NULL"):0;
$add('Demo','Demonstração isolada registrada',$demoTenants===1,$demoTenants.' tenant(s) demo','warning');
$demoBilling=0;
if($demoColumn){
    $demoBilling += $count("SELECT COUNT(*) FROM payments p JOIN tenants t ON t.id=p.tenant_id WHERE t.is_demo=1");
    $demoBilling += $count("SELECT COUNT(*) FROM tenant_payment_connections c JOIN tenants t ON t.id=c.tenant_id WHERE t.is_demo=1");
    $demoBilling += $count("SELECT COUNT(*) FROM tenant_payment_transactions x JOIN tenants t ON t.id=x.tenant_id WHERE t.is_demo=1");
}
$add('Demo','Sem evidência financeira real na demo',$demoBilling===0,$demoBilling.' registro(s) de billing real na demo','warning');

// Testes existentes + RC1
$testFiles=[
    'tests/route_integrity_static.php',
    'tests/security_static.php',
    'tests/auth_security_static.php',
    'tests/commercial_security_static.php',
    'tests/subscription_access_test.php',
    'tests/arena_v2_smoke.php',
    'tests/barber_v1_smoke.php',
    'tests/barber_recurring_provider_unit.php',
    'tests/auto_v1_smoke.php',
    'tests/module_subscription_merge_smoke.php',
    'tests/mercadopago_subscription_update_unit.php',
    'tests/mercadopago_card_provider_unit.php',
    'tests/two_factor_trusted_device_static.php',
    'tests/demo_commercial_smoke.php',
    'tests/rc1_regression_static.php',
];
foreach($testFiles as $tf){
    if(!is_file($root.'/'.$tf)){$add('Testes',$tf,false,'arquivo ausente');continue;}
    $o=[];$c=0;@exec(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/'.$tf).' 2>&1',$o,$c);
    $add('Testes',$tf,$c===0,mb_substr(implode(' | ',$o),0,500));
}

// Aceites funcionais: só bloqueiam o GO comercial, nunca são preenchidos automaticamente.
$requiredAcceptance=[
    'tenant_idor','billing_e2e','billing_module','agenda','barber','arena_concurrency',
    'arena_payment','auto','two_factor','lgpd'
];
$accept=[];
$file=$root.'/storage/private/rc1-acceptance.json';
if(is_file($file)){$d=json_decode((string)file_get_contents($file),true);if(is_array($d))$accept=$d['checks']??[];}
foreach($requiredAcceptance as $key){
    $done=!empty($accept[$key]['passed']);
    $add('Homologação',"Aceite {$key}",$done,$done?($accept[$key]['at']??'registrado'):'pendente',$commercial?'blocker':'warning');
}

$blockers=array_values(array_filter($checks,fn($c)=>$c['level']==='blocker'&&!$c['ok']));
$warnings=array_values(array_filter($checks,fn($c)=>$c['level']==='warning'&&!$c['ok']));
if($commercial){$verdict=$blockers?'NO-GO COMERCIAL':'GO COMERCIAL';}
else{$verdict=$blockers?'NO-GO TÉCNICO':'GO TÉCNICO';}

$stamp=date('Ymd-His');$dir=$root.'/storage/logs';if(!is_dir($dir))@mkdir($dir,0750,true);
$md="# APPLANNER RC1 — GO LIVE\n\n";
$md.="- Data: **".date('d/m/Y H:i:s')."**\n- Modo: **".($commercial?'COMERCIAL':'TÉCNICO')."**\n- Externo: **".($external?'SIM':'NÃO')."**\n- Veredito: **{$verdict}**\n\n";
$md.="| Área | Check | Status | Detalhes |\n|---|---|---|---|\n";
foreach($checks as $c)$md.='| '.str_replace('|','/',$c['area']).' | '.str_replace('|','/',$c['name']).' | '.($c['ok']?'✅':'❌').' | '.str_replace(["|","\n"],['/',' '],$c['details'])." |\n";
$md.="\n## Bloqueadores\n\n";
if(!$blockers)$md.="Nenhum bloqueador.\n"; else foreach($blockers as $c)$md.="- **{$c['area']} / {$c['name']}** — {$c['details']}\n";
$md.="\n## Avisos\n\n";
if(!$warnings)$md.="Nenhum aviso.\n"; else foreach($warnings as $c)$md.="- {$c['area']} / {$c['name']} — {$c['details']}\n";
$md.="\n> O selo GO COMERCIAL só é emitido com `--commercial --external`, evidência técnica de billing/webhooks/pagamentos e todos os aceites funcionais registrados.\n";
$mdFile=$dir."/rc1-go-live-{$stamp}.md";$jsonFile=$dir."/rc1-go-live-{$stamp}.json";
file_put_contents($mdFile,$md,LOCK_EX);
file_put_contents($jsonFile,json_encode(['verdict'=>$verdict,'commercial'=>$commercial,'external'=>$external,'checks'=>$checks,'blockers'=>$blockers,'warnings'=>$warnings],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES),LOCK_EX);

echo "APPLANNER RC1 - {$verdict}\n";
echo "Bloqueadores: ".count($blockers)." | Avisos: ".count($warnings)."\n";
foreach($blockers as $c)echo "[BLOQUEADOR] {$c['area']} / {$c['name']}: {$c['details']}\n";
echo "\nRelatório: {$mdFile}\n";
exit($blockers?2:0);
