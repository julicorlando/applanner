<?php
declare(strict_types=1);

/**
 * ApPlanner - Auditoria Geral Read-Only v1.0
 *
 * Uso:
 *   php tools/auditoria-applanner.php
 *   php tools/auditoria-applanner.php --deep
 *
 * Saídas:
 *   storage/logs/auditoria-applanner-YYYYmmdd-His.md
 *   storage/logs/auditoria-applanner-YYYYmmdd-His.json
 *
 * Segurança:
 * - Não altera banco.
 * - Não altera arquivos da aplicação.
 * - Não exibe senhas, Access Tokens ou secrets.
 * - Deve ser executado apenas pela CLI.
 */

if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    exit("Execute este auditor somente via CLI.\n");
}

$root = realpath(dirname(__DIR__)) ?: dirname(__DIR__);
$deep = in_array('--deep', $argv, true);
$started = microtime(true);
$stamp = date('Ymd-His');
$outDir = is_dir($root . '/storage/logs') && is_writable($root . '/storage/logs')
    ? $root . '/storage/logs'
    : sys_get_temp_dir();
$mdPath = $outDir . "/auditoria-applanner-{$stamp}.md";
$jsonPath = $outDir . "/auditoria-applanner-{$stamp}.json";

$R = [
    'meta' => [], 'environment' => [], 'filesystem' => [], 'database' => [],
    'migrations' => [], 'routes' => [], 'crons' => [], 'billing' => [],
    'security' => [], 'features' => [], 'logs' => [], 'backups' => [],
    'quality' => [], 'findings' => [], 'summary' => [],
];

function addFinding(array &$R, string $sev, string $area, string $msg, string $evidence=''): void {
    $R['findings'][] = ['severity'=>strtoupper($sev),'area'=>$area,'message'=>$msg,'evidence'=>$evidence];
}
function yesno(bool $v): string { return $v ? 'SIM' : 'NÃO'; }
function red(string $s): string {
    $patterns = [
        '/(?i)(access[_-]?token|client[_-]?secret|secret|password|passwd|senha|api[_-]?key|private[_-]?key|authorization)\s*[:=]\s*[^\s,;]+/',
        '/(?i)Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*/',
        '/TEST-[A-Za-z0-9\-_]+/', '/APP_USR-[A-Za-z0-9\-_]+/'
    ];
    foreach ($patterns as $p) $s = preg_replace($p, '$1=[REDACTED]', $s) ?? $s;
    return $s;
}
function shellSafe(string $cmd): string {
    if (!function_exists('shell_exec')) return '';
    $x = @shell_exec($cmd . ' 2>&1');
    return is_string($x) ? trim($x) : '';
}
function rel(string $root, string $path): string {
    $path = str_replace('\\','/',$path); $root = str_replace('\\','/',$root);
    return str_starts_with($path,$root.'/') ? substr($path,strlen($root)+1) : $path;
}
function phpFiles(string $root): array {
    $out=[]; $it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root,FilesystemIterator::SKIP_DOTS));
    foreach($it as $f){
        if(!$f->isFile() || strtolower($f->getExtension())!=='php') continue;
        $r=rel($root,$f->getPathname());
        if(preg_match('~^(vendor|node_modules|\.git|storage/backups|storage/cache)/~',$r)) continue;
        $out[]=$f->getPathname();
    }
    sort($out); return $out;
}
function migrationFiles(string $root): array {
    $out=[];
    foreach([$root.'/database/migrations',$root.'/migrations',$root.'/database/sql',$root.'/sql/migrations'] as $d){
        if(!is_dir($d)) continue;
        foreach(glob($d.'/*.{sql,php}',GLOB_BRACE)?:[] as $f) $out[]=rel($root,$f);
    }
    sort($out); return array_values(array_unique($out));
}
function detectBootstrap(string $root): ?string {
    foreach([$root.'/app/Core/bootstrap.php',$root.'/app/Core/Bootstrap.php',$root.'/bootstrap.php',$root.'/config/bootstrap.php',$root.'/app/bootstrap.php'] as $f)
        if(is_file($f)) return $f;
    return null;
}
function dbFromApp(string $root, ?string &$how=null): ?PDO {
    $b=detectBootstrap($root);
    if(!$b){$how='bootstrap não localizado';return null;}
    try{
        require_once $b;
        if(class_exists('\\App\\Core\\Database') && method_exists('\\App\\Core\\Database','connection')){
            $pdo=\App\Core\Database::connection();
            if($pdo instanceof PDO){$how='App\\Core\\Database::connection()';return $pdo;}
        }
        $how='classe App\\Core\\Database não disponível';
    }catch(Throwable $e){$how='bootstrap falhou: '.$e->getMessage();}
    return null;
}
function tableExists(PDO $pdo,string $db,string $table): bool {
    $q=$pdo->prepare('SELECT 1 FROM information_schema.tables WHERE table_schema=? AND table_name=? LIMIT 1');
    $q->execute([$db,$table]); return (bool)$q->fetchColumn();
}
function columns(PDO $pdo,string $db,string $table): array {
    $q=$pdo->prepare('SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position');
    $q->execute([$db,$table]); return $q->fetchAll(PDO::FETCH_COLUMN)?:[];
}
function scanNeedles(string $root,array $needles,array $ext=['php','sql','js','md']): array {
    $hits=[]; foreach($needles as $n)$hits[$n]=[];
    $it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root,FilesystemIterator::SKIP_DOTS));
    foreach($it as $f){
        if(!$f->isFile() || !in_array(strtolower($f->getExtension()),$ext,true) || $f->getSize()>3000000) continue;
        $r=rel($root,$f->getPathname());
        if(preg_match('~^(vendor|node_modules|\.git)/~',$r)) continue;
        $c=@file_get_contents($f->getPathname()); if(!is_string($c))continue;
        foreach($needles as $n) if(stripos($c,$n)!==false && count($hits[$n])<15)$hits[$n][]=$r;
    }
    return $hits;
}
function envFlags(string $root): array {
    $out=[];
    foreach([$root.'/.env',$root.'/.env.local',$root.'/config/.env'] as $f){
        if(!is_readable($f))continue;
        foreach(file($f,FILE_IGNORE_NEW_LINES|FILE_SKIP_EMPTY_LINES)?:[] as $line){
            $line=trim($line); if($line===''||str_starts_with($line,'#')||!str_contains($line,'='))continue;
            [$k,$v]=array_map('trim',explode('=',$line,2));
            if(!preg_match('/APP_|DB_|DATABASE_|MAIL_|SMTP_|MERCADO|MP_|WHATSAPP|META_|ASAAS|EFI|INTER_|OPEN_FINANCE|SESSION|COOKIE|2FA|TOTP|ENCRYPT|KEY/i',$k))continue;
            $v=trim($v," \t\n\r\0\x0B\"'");
            $out[$k]=$v!==''&&!in_array(strtolower($v),['null','changeme','change_me','example'],true);
        }
    }
    ksort($out); return $out;
}
function routes(string $root): array {
    $files=[];
    foreach([$root.'/index.php',$root.'/public/index.php',$root.'/routes.php',$root.'/app/routes.php',$root.'/routes/web.php',$root.'/config/routes.php'] as $f) if(is_file($f))$files[]=$f;
    foreach(glob($root.'/routes/*.php')?:[] as $f)$files[]=$f;
    $out=[];
    foreach(array_unique($files) as $f){
        $c=@file_get_contents($f); if(!is_string($c))continue;
        if(preg_match_all('/\$[A-Za-z_][A-Za-z0-9_]*->(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]/i',$c,$m,PREG_SET_ORDER)){
            foreach($m as $x)$out[]=['method'=>strtoupper($x[1]),'path'=>$x[2],'file'=>rel($root,$f)];
        }
        if(preg_match_all('/Route::(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]/i',$c,$m,PREG_SET_ORDER)){
            foreach($m as $x)$out[]=['method'=>strtoupper($x[1]),'path'=>$x[2],'file'=>rel($root,$f)];
        }
    }
    $u=[]; foreach($out as $r)$u[$r['method'].' '.$r['path'].' '.$r['file']]=$r;
    return array_values($u);
}
function tailFile(string $f,int $max=250000): string {
    if(!is_readable($f))return '';$s=filesize($f);$h=fopen($f,'rb');if(!$h)return'';
    if($s>$max)fseek($h,-$max,SEEK_END);$d=stream_get_contents($h);fclose($h);return is_string($d)?$d:'';
}
function mdEsc(string $s): string {return str_replace('|','\\|',str_replace(["\r","\n"],['',' '],$s));}

$R['meta']=['generated_at'=>date(DATE_ATOM),'root'=>$root,'deep'=>$deep,'version'=>'1.0.0'];
$R['environment']=[
    'php'=>PHP_VERSION,'os'=>PHP_OS_FAMILY,'uname'=>php_uname(),'memory_limit'=>ini_get('memory_limit'),
    'display_errors'=>ini_get('display_errors'),'timezone'=>date_default_timezone_get(),
    'extensions'=>['pdo_mysql'=>extension_loaded('pdo_mysql'),'curl'=>extension_loaded('curl'),'openssl'=>extension_loaded('openssl'),'mbstring'=>extension_loaded('mbstring')]
];
if(filter_var(ini_get('display_errors'),FILTER_VALIDATE_BOOL))addFinding($R,'MEDIO','Ambiente','display_errors está habilitado em CLI/configuração atual.');

$php=phpFiles($root);$ctx=hash_init('sha256');$bytes=0;
foreach($php as $f){$bytes+=filesize($f)?:0;hash_update($ctx,rel($root,$f));$h=@fopen($f,'rb');if($h){while(!feof($h)){ $b=fread($h,1048576);if($b===false)break;hash_update($ctx,$b);}fclose($h);}}
$R['filesystem']=[
    'php_files'=>count($php),'php_bytes'=>$bytes,'aggregate_php_sha256'=>hash_final($ctx),
    'bootstrap'=>($b=detectBootstrap($root))?rel($root,$b):null,'env_flags'=>envFlags($root),
    'writable'=>['root'=>is_writable($root),'storage'=>is_dir($root.'/storage')?is_writable($root.'/storage'):null,'logs'=>is_dir($root.'/storage/logs')?is_writable($root.'/storage/logs'):null]
];
if(!$R['filesystem']['bootstrap'])addFinding($R,'ALTO','Bootstrap','Bootstrap conhecido não foi localizado.');

$dbHow=null;$pdo=dbFromApp($root,$dbHow);$db=null;$tables=[];
$R['database']['connected']=$pdo instanceof PDO;$R['database']['connection_method']=$dbHow;
if($pdo){
    try{
        $db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();$R['database']['name']=$db;$R['database']['version']=$pdo->getAttribute(PDO::ATTR_SERVER_VERSION);
        $q=$pdo->prepare('SELECT table_name,engine,table_rows,table_collation FROM information_schema.tables WHERE table_schema=? ORDER BY table_name');$q->execute([$db]);$tables=$q->fetchAll(PDO::FETCH_ASSOC)?:[];
        $R['database']['tables']=$tables;$R['database']['table_count']=count($tables);
        $q=$pdo->prepare('SELECT constraint_name,table_name,referenced_table_name FROM information_schema.key_column_usage WHERE table_schema=? AND referenced_table_name IS NOT NULL ORDER BY constraint_name');$q->execute([$db]);
        $fks=$q->fetchAll(PDO::FETCH_ASSOC)?:[];$R['database']['foreign_keys']=$fks;
        $map=[];foreach($fks as $fk)$map[$fk['constraint_name']][]=$fk;$dups=array_filter($map,fn($x)=>count($x)>1);$R['database']['duplicate_fk_names']=$dups;
        if($dups)addFinding($R,'ALTO','Banco','Nomes de Foreign Key repetidos detectados.',implode(', ',array_keys($dups)));
        $counts=[];foreach(['tenants','users','customers','professionals','services','appointments','subscriptions','payments','products','financial_entries','sports_reservations','sports_commands','two_factor_trusted_devices','auto_vehicles','auto_boxes','auto_work_orders','auto_commands','barber_commands','barber_queue'] as $t){
            if(tableExists($pdo,$db,$t))try{$counts[$t]=(int)$pdo->query("SELECT COUNT(*) FROM `{$t}`")->fetchColumn();}catch(Throwable $e){$counts[$t]='ERRO';}
        }$R['database']['selected_counts']=$counts;
        $tenant=[];foreach($tables as $t){$name=$t['table_name'];$tenant[$name]=in_array('tenant_id',columns($pdo,$db,$name),true);}$R['database']['tenant_id_presence']=$tenant;
    }catch(Throwable $e){$R['database']['error']=$e->getMessage();addFinding($R,'ALTO','Banco','Leitura do schema falhou.',$e->getMessage());}
}else addFinding($R,'ALTO','Banco','Não foi possível obter conexão PDO via aplicação.',(string)$dbHow);

$migs=migrationFiles($root);$R['migrations']['files']=$migs;$R['migrations']['count']=count($migs);
$expected=['037'=>'Arena base','038'=>'Arena V2','039'=>'Módulos na assinatura','040'=>'Barber V1','041'=>'Auto V1','042'=>'2FA 30 dias'];
foreach($expected as $p=>$d){$found=array_values(array_filter($migs,fn($f)=>preg_match('~(?:^|/)'.preg_quote($p,'~').'[_-]~',$f)));$R['migrations']['expected'][$p]=['description'=>$d,'present'=>(bool)$found,'files'=>$found];}
$R['migrations']['applied_tables']=[];
if($pdo&&$db){foreach(['migrations','schema_migrations','migration_versions'] as $mt){if(!tableExists($pdo,$db,$mt))continue;try{$R['migrations']['applied_tables'][$mt]=$pdo->query("SELECT * FROM `{$mt}` ORDER BY 1")->fetchAll(PDO::FETCH_ASSOC)?:[];}catch(Throwable $e){}}}

$rts=routes($root);$R['routes']['items']=$rts;$R['routes']['count']=count($rts);$by=[];foreach($rts as $r)$by[$r['method'].' '.$r['path']][]=$r['file'];$rdup=[];foreach($by as $k=>$v)if(count($v)>1)$rdup[$k]=$v;$R['routes']['duplicates']=$rdup;if($rdup)addFinding($R,'MEDIO','Rotas','Possíveis rotas duplicadas detectadas.',count($rdup).' duplicidades');
foreach(['arena'=>'~^/arena/~','auto'=>'~^/auto/~','sports_commands'=>'~^/sports/commands~','barber'=>'~barber~i','2fa'=>'~2fa|two.?factor|trusted~i','modules'=>'~module|modulo|módulo~iu'] as $k=>$rx)$R['routes']['critical'][$k]=array_values(array_filter($rts,fn($r)=>preg_match($rx,$r['path'])));

$cronFiles=[];foreach(['cron/arena.php','cron/barber.php','cron/auto.php','cron.php'] as $f)$cronFiles[$f]=is_file($root.'/'.$f);$ct=shellSafe('crontab -l');$R['crons']=['files'=>$cronFiles,'crontab_visible'=>$ct!=='','crontab_redacted'=>$ct!==''?red($ct):null];

$needles=['sports_reservations','sports_commands','dynamic_price','barber_queue','barber_commands','chair_rental','auto_vehicles','auto_boxes','auto_work','applanner-auto-demo','two_factor_trusted_devices','trusted_device','merged_subscription','subscription_module_adjustments','module_requests','preapproval','x-signature','idempotency','external_reference'];
$hits=scanNeedles($root,$needles);$R['features']['hits']=$hits;$tableNames=array_column($tables,'table_name');
$defs=[
 'Arena'=>['m'=>['037','038'],'t'=>['sports_reservations','sports_commands'],'f'=>['cron/arena.php'],'r'=>'~^/arena/~','n'=>['sports_reservations']],
 'Módulos na assinatura'=>['m'=>['039'],'t'=>['subscription_module_adjustments','module_requests'],'n'=>['merged_subscription','subscription_module_adjustments']],
 'Barber'=>['m'=>['040'],'t'=>['barber_commands','barber_queue'],'f'=>['cron/barber.php'],'n'=>['barber_queue','chair_rental']],
 'Auto'=>['m'=>['041'],'t'=>['auto_vehicles','auto_boxes','auto_work_orders'],'f'=>['cron/auto.php'],'r'=>'~^/auto/~','n'=>['auto_vehicles','auto_boxes']],
 'Demo comercial Auto'=>['n'=>['applanner-auto-demo']],
 '2FA dispositivo 30 dias'=>['m'=>['042'],'t'=>['two_factor_trusted_devices'],'n'=>['two_factor_trusted_devices','trusted_device']],
];
foreach($defs as $name=>$d){$score=0;$max=0;$ev=[];
 if(isset($d['m']))foreach($d['m'] as $p){$max++;if(!empty($R['migrations']['expected'][$p]['present'])){$score++;$ev[]="migration {$p}";}}
 if(isset($d['t'])){$max++;$x=array_values(array_intersect($d['t'],$tableNames));if($x){$score++;$ev[]='tabelas: '.implode(', ',$x);}}
 if(isset($d['f'])){$max++;$x=array_values(array_filter($d['f'],fn($f)=>is_file($root.'/'.$f)));if($x){$score++;$ev[]='arquivos: '.implode(', ',$x);}}
 if(isset($d['r'])){$max++;$x=array_values(array_filter($rts,fn($r)=>preg_match($d['r'],$r['path'])));if($x){$score++;$ev[]=count($x).' rota(s)';}}
 if(isset($d['n'])){$max++;$x=[];foreach($d['n'] as $n)if(!empty($hits[$n]))$x[]=$n;if($x){$score++;$ev[]='código: '.implode(', ',$x);}}
 $st=$score===0?'AUSENTE':($score===$max?'IMPLEMENTADO':'PARCIAL');$R['features']['status'][$name]=['status'=>$st,'score'=>"{$score}/{$max}",'evidence'=>$ev];
}

$env=$R['filesystem']['env_flags'];$bk=[];foreach($env as $k=>$v)if(preg_match('/MERCADO|MP_|ASAAS|EFI|INTER_|OPEN_FINANCE/i',$k))$bk[$k]=$v;
$R['billing']=['config_flags'=>$bk,'code'=>['preapproval'=>!empty($hits['preapproval']),'webhook_signature'=>!empty($hits['x-signature']),'idempotency'=>!empty($hits['idempotency']),'external_reference'=>!empty($hits['external_reference'])]];
if(!$R['billing']['code']['idempotency'])addFinding($R,'ALTO','Billing','Indicador de idempotência não encontrado estaticamente.');

$secN=['csrf','password_hash','password_verify','session_regenerate_id','tenant_id','session_version','totp','two_factor','HttpOnly','SameSite','Secure','eval(','base64_decode(','shell_exec(','exec(','system('];$sec=scanNeedles($root,$secN,['php']);$R['security']['hits']=$sec;$R['security']['trusted_devices_table']=in_array('two_factor_trusted_devices',$tableNames,true);
if(empty($sec['csrf']))addFinding($R,'ALTO','Segurança','Indicador CSRF não encontrado; validar proteção manualmente.');
if(empty($sec['password_hash']))addFinding($R,'ALTO','Segurança','password_hash não encontrado estaticamente.');
if(empty($sec['session_regenerate_id']))addFinding($R,'MEDIO','Segurança','session_regenerate_id não encontrado; revisar fixação de sessão.');
foreach(['eval(','base64_decode(','shell_exec(','exec(','system('] as $n)if(!empty($sec[$n]))$R['security']['dangerous'][$n]=$sec[$n];

$logs=[];foreach([$root.'/error_log',$root.'/storage/logs/error.log',$root.'/storage/logs/app.log',$root.'/storage/logs/cron.log',$root.'/storage/logs/arena-cron.log',$root.'/storage/logs/barber-cron.log',$root.'/storage/logs/auto-cron.log'] as $f)if(is_file($f))$logs[]=$f;foreach(glob($root.'/storage/logs/*.log')?:[] as $f)$logs[]=$f;$logs=array_values(array_unique($logs));
$sum=[];foreach($logs as $f){$d=tailFile($f);if($d==='')continue;$c=[];foreach(['Fatal'=>'/Fatal error|Uncaught/i','SQLSTATE'=>'/SQLSTATE/i','Warning'=>'/\bWarning\b/i','500'=>'/\b500\b/','404'=>'/\b404\b/','MP400502'=>'/(mercado.?pago|preapproval|payment).{0,100}\b(400|502)\b/i'] as $n=>$rx){preg_match_all($rx,$d,$m);if(count($m[0]))$c[$n]=count($m[0]);}if($c){$lines=preg_split('/\R/',red($d))?:[];$interesting=array_values(array_filter($lines,fn($l)=>preg_match('/Fatal|Uncaught|SQLSTATE|Warning|\b500\b|\b502\b|\b400\b/i',$l)));$sum[rel($root,$f)]=['counts'=>$c,'sample'=>array_slice($interesting,-8)];}}
$R['logs']=['checked'=>array_map(fn($f)=>rel($root,$f),$logs),'summary'=>$sum];if($sum)addFinding($R,'MEDIO','Logs','Erros/warnings recentes encontrados; revisar amostras.');

$backup=[];foreach([$root.'/backup',$root.'/backups',$root.'/storage/backups',dirname($root).'/backups'] as $d){if(!is_dir($d))continue;foreach(glob($d.'/*')?:[] as $f)if(is_file($f))$backup[]=['path'=>$f,'mtime'=>filemtime($f),'size'=>filesize($f)];}usort($backup,fn($a,$b)=>$b['mtime']<=>$a['mtime']);$R['backups']['recent']=array_slice($backup,0,20);if(!$backup)addFinding($R,'MEDIO','Backup','Backup não localizado nas pastas padrão; pode existir backup externo/cPanel.');

$lint=[];if($deep){foreach($php as $f){$o=shellSafe(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($f));if(stripos($o,'No syntax errors detected')===false){$lint[]=['file'=>rel($root,$f),'output'=>red($o)];if(count($lint)>=100)break;}}}
$R['quality']=['deep'=>$deep,'php_scanned'=>count($php),'lint_errors'=>$lint];if($deep&&$lint)addFinding($R,'ALTO','Qualidade','Erros de sintaxe PHP encontrados.',count($lint).' arquivo(s)');

$weights=['CRITICO'=>25,'ALTO'=>12,'MEDIO'=>5,'BAIXO'=>2];$pen=0;foreach($R['findings'] as $f)$pen+=$weights[$f['severity']]??1;$confidence=max(0,min(100,100-$pen));
$impl=0;$part=0;$tot=count($R['features']['status']);foreach($R['features']['status'] as $f){if($f['status']==='IMPLEMENTADO')$impl++;elseif($f['status']==='PARCIAL')$part++;}$coverage=$tot?round((($impl+0.5*$part)/$tot)*100):0;
$verdict='GO COM RESSALVAS';if($confidence>=90&&$pdo&&(!$deep||!$lint))$verdict='GO TÉCNICO — AINDA REQUER HOMOLOGAÇÃO FUNCIONAL';if($confidence<60||($deep&&$lint))$verdict='NO-GO ATÉ CORREÇÕES';
$R['summary']=['feature_coverage_indicator'=>$coverage,'production_confidence_indicator'=>$confidence,'verdict'=>$verdict,'note'=>'Indicadores heurísticos; não substituem homologação funcional, financeira, LGPD ou pentest.'];

$M=[];$M[]='# APPLANNER — RELATÓRIO AUTOMÁTICO DE AUDITORIA';$M[]='';$M[]='- Gerado em: **'.date('d/m/Y H:i:s').'**';$M[]='- Raiz: `'.mdEsc($root).'`';$M[]='- Modo: **'.($deep?'DEEP':'NORMAL').'**';$M[]='- PHP: **'.PHP_VERSION.'**';$M[]='- Veredito automático: **'.$verdict.'**';$M[]='- Cobertura funcional detectada: **'.$coverage.'%**';$M[]='- Confiança técnica automática: **'.$confidence.'%**';$M[]='';$M[]='> O relatório é somente leitura e não expõe segredos. Envie este arquivo para avaliação final.';$M[]='';
$M[]='## 1. Ambiente';$M[]='';$M[]='| Item | Valor |';$M[]='|---|---|';$M[]='| PHP | '.PHP_VERSION.' |';$M[]='| SO | '.mdEsc(PHP_OS_FAMILY).' |';$M[]='| Bootstrap | '.mdEsc((string)($R['filesystem']['bootstrap']??'não localizado')).' |';$M[]='| Banco conectado | '.yesno((bool)$R['database']['connected']).' |';$M[]='| Banco | '.mdEsc((string)($R['database']['name']??'N/D')).' |';$M[]='| Versão banco | '.mdEsc((string)($R['database']['version']??'N/D')).' |';$M[]='| PHPs | '.count($php).' |';$M[]='| Hash agregado | `'.$R['filesystem']['aggregate_php_sha256'].'` |';$M[]='';
$M[]='### Flags de configuração — apenas presença';foreach($env as $k=>$v)$M[]='- `'.mdEsc($k).'`: **'.($v?'configurado':'vazio/placeholder').'**';$M[]='';
$M[]='## 2. Migrations';$M[]='';$M[]='| Migration | Finalidade | Presença |';$M[]='|---|---|---|';foreach($R['migrations']['expected'] as $p=>$i)$M[]='| '.$p.' | '.mdEsc($i['description']).' | '.($i['present']?'✅ '.mdEsc(implode(', ',$i['files'])):'⚪ não localizada').' |';$M[]='';$M[]='- Total de migrations encontradas: **'.count($migs).'**';$M[]='- Controle de migrations detectado: **'.($R['migrations']['applied_tables']?mdEsc(implode(', ',array_keys($R['migrations']['applied_tables']))):'nenhum reconhecido').'**';$M[]='';
$M[]='## 3. Funcionalidades detectadas';$M[]='';$M[]='| Área | Status | Evidências |';$M[]='|---|---|---|';foreach($R['features']['status'] as $n=>$f){$emo=$f['status']==='IMPLEMENTADO'?'✅':($f['status']==='PARCIAL'?'🟡':'⚪');$M[]='| '.mdEsc($n).' | '.$emo.' '.$f['status'].' '.$f['score'].' | '.mdEsc(implode('; ',$f['evidence'])?:'nenhuma').' |';}$M[]='';
$M[]='## 4. Banco';$M[]='';$M[]='- Tabelas: **'.($R['database']['table_count']??0).'**';$M[]='- Foreign Keys: **'.count($R['database']['foreign_keys']??[]).'**';$M[]='- Colisões de FK: **'.count($R['database']['duplicate_fk_names']??[]).'**';$M[]='';if(!empty($R['database']['selected_counts'])){$M[]='### Contagens selecionadas';$M[]='';$M[]='| Tabela | Registros |';$M[]='|---|---:|';foreach($R['database']['selected_counts'] as $t=>$c)$M[]='| `'.$t.'` | '.$c.' |';$M[]='';}
$M[]='## 5. Rotas';$M[]='';$M[]='- Rotas detectadas: **'.count($rts).'**';$M[]='- Duplicidades: **'.count($rdup).'**';foreach($R['routes']['critical'] as $k=>$v)$M[]='- `'.$k.'`: **'.count($v).'** rota(s)';if($rdup){$M[]='';$M[]='### Possíveis duplicidades';foreach($rdup as $k=>$v)$M[]='- `'.mdEsc($k).'` — '.mdEsc(implode(', ',$v));}$M[]='';
$M[]='## 6. Billing';$M[]='';$M[]='| Controle | Detectado |';$M[]='|---|---|';foreach($R['billing']['code'] as $k=>$v)$M[]='| '.$k.' | '.($v?'✅':'⚪').' |';$M[]='';$M[]='### Credenciais/configuração — somente presença';foreach($bk as $k=>$v)$M[]='- `'.$k.'`: **'.($v?'configurado':'vazio/placeholder').'**';if(!$bk)$M[]='- Nenhuma flag financeira conhecida detectada.';$M[]='';
$M[]='## 7. Segurança';$M[]='';$M[]='- `tenant_id` encontrado em **'.count($sec['tenant_id']??[]).'** arquivos';$M[]='- `two_factor_trusted_devices`: **'.yesno((bool)$R['security']['trusted_devices_table']).'**';$M[]='- CSRF detectado: **'.yesno(!empty($sec['csrf'])).'**';$M[]='- password_hash: **'.yesno(!empty($sec['password_hash'])).'**';$M[]='- password_verify: **'.yesno(!empty($sec['password_verify'])).'**';$M[]='- session_regenerate_id: **'.yesno(!empty($sec['session_regenerate_id'])).'**';if(!empty($R['security']['dangerous'])){$M[]='';$M[]='### Funções a revisar';foreach($R['security']['dangerous'] as $k=>$v)$M[]='- `'.$k.'`: '.mdEsc(implode(', ',$v));}$M[]='';
$M[]='## 8. Crons';$M[]='';foreach($cronFiles as $f=>$v)$M[]='- `'.$f.'`: '.($v?'✅ existe':'⚪ ausente');$M[]='- crontab visível: **'.yesno($ct!=='').'**';if($ct!==''){$M[]='';$M[]='```text';$M[]=red($ct);$M[]='```';}$M[]='';
$M[]='## 9. Logs recentes';$M[]='';if(!$sum)$M[]='- Nenhum padrão crítico encontrado nos trechos recentes.';else foreach($sum as $f=>$i){$M[]='### `'.mdEsc($f).'`';foreach($i['counts'] as $k=>$v)$M[]='- '.$k.': **'.$v.'**';if($i['sample']){$M[]='```text';foreach($i['sample'] as $l)$M[]=mb_substr($l,0,1000);$M[]='```';}}$M[]='';
$M[]='## 10. Backups';$M[]='';if(!$backup)$M[]='- Nenhum backup localizado nas pastas padrão.';else foreach(array_slice($backup,0,20) as $b)$M[]='- `'.mdEsc($b['path']).'` — '.date('d/m/Y H:i:s',$b['mtime']).' — '.$b['size'].' bytes';$M[]='';
$M[]='## 11. Qualidade';$M[]='';$M[]='- PHPs inventariados: **'.count($php).'**';$M[]='- Modo deep: **'.yesno($deep).'**';if($deep){$M[]='- Erros de lint: **'.count($lint).'**';foreach($lint as $e)$M[]='- `'.mdEsc($e['file']).'`: '.mdEsc($e['output']);}else $M[]='- Rode com `--deep` para lint de todos os PHPs.';$M[]='';
$M[]='## 12. Achados automáticos';$M[]='';if(!$R['findings'])$M[]='✅ Nenhum achado relevante.';else{$ord=['CRITICO'=>0,'ALTO'=>1,'MEDIO'=>2,'BAIXO'=>3];usort($R['findings'],fn($a,$b)=>($ord[$a['severity']]??9)<=>($ord[$b['severity']]??9));$M[]='| Severidade | Área | Achado | Evidência |';$M[]='|---|---|---|---|';foreach($R['findings'] as $f)$M[]='| '.$f['severity'].' | '.mdEsc($f['area']).' | '.mdEsc($f['message']).' | '.mdEsc($f['evidence']).' |';}$M[]='';
$M[]='## 13. Checklist manual obrigatório';$M[]='';foreach(['Isolamento IDOR entre Empresa A e Empresa B','Cadastro → plano → assinatura → pagamento → webhook → ativação','Renovação, falha de cobrança, upgrade e downgrade','Módulo solicitado → aprovado → valor incorporado → liberação','Agenda: criar, confirmar, remarcar e cancelar','Barber: check-in → comanda → estoque → comissão → financeiro','Arena: duas reservas simultâneas na mesma quadra/horário; apenas uma vence','Arena: sinal/pagamento/conciliação','Auto: veículo → box → check-in → checklist/fotos → orçamento → comanda → entrega','2FA 30 dias → logout → login sem TOTP → revogação → TOTP obrigatório','Restauração real de backup em ambiente de teste','LGPD: versão dos termos, aceite, finalidade, consentimento e revogação','Pentest/revisão para SQLi, XSS, CSRF, IDOR, auth bypass, upload e SSRF'] as $x)$M[]='- [ ] '.$x;$M[]='';
$M[]='## 14. Conclusão automática';$M[]='';$M[]='**'.$verdict.'**';$M[]='';$M[]='- Cobertura funcional detectada: **'.$coverage.'%**';$M[]='- Confiança técnica automática: **'.$confidence.'%**';$M[]='';$M[]='> Envie este `.md` para o ChatGPT. A avaliação final deve cruzar este relatório com o histórico do projeto e os testes funcionais.';$M[]='';

$R['meta']['elapsed_seconds']=round(microtime(true)-$started,3);$md=implode("\n",$M)."\n";
file_put_contents($mdPath,$md);file_put_contents($jsonPath,json_encode($R,JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE));

echo "APPLANNER - AUDITORIA FINALIZADA\n";
echo "================================\n";
echo "Modo: ".($deep?'DEEP':'NORMAL')."\n";
echo "PHPs: ".count($php)."\n";
echo "Banco conectado: ".yesno($pdo instanceof PDO)."\n";
echo "Cobertura funcional detectada: {$coverage}%\n";
echo "Confiança técnica automática: {$confidence}%\n";
echo "Veredito: {$verdict}\n\n";
echo "RELATÓRIO MARKDOWN:\n{$mdPath}\n\n";
echo "RELATÓRIO JSON:\n{$jsonPath}\n\n";
echo "Para auditoria mais completa:\nphp tools/auditoria-applanner.php --deep\n\n";
echo "Depois envie o arquivo .md aqui.\n";
