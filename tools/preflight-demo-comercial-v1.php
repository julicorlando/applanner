<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);require $root.'/app/Core/bootstrap.php';
use App\Core\Database;
$fail=[];$warn=[];$ok=[];$check=function(bool $v,string $msg,bool $warning=false)use(&$fail,&$warn,&$ok){if($v)$ok[]=$msg;elseif($warning)$warn[]=$msg;else$fail[]=$msg;};
$check(version_compare(PHP_VERSION,'8.2','>='),'PHP 8.2+');
foreach(['index.php','app/Views/commercial/landing.php','public/assets/css/index-conversion.css','public/assets/js/index-conversion.js','app/Views/layout.php'] as $f)$check(is_file($root.'/'.$f),'Arquivo presente: '.$f);
$payload=$root.'/patches/applanner-demo-comercial-v1/payload';foreach(['app/Views/commercial/landing.php','public/assets/css/index-conversion.css','public/assets/js/index-conversion.js','tools/demo-auto-company.php','tests/demo_commercial_smoke.php'] as $f)$check(is_file($payload.'/'.$f),'Payload: '.$f);
try{$pdo=Database::connection();$tables=['tenants','users','roles','subscriptions','units','services','customers','customer_vehicles','professionals','auto_settings','auto_service_bays','auto_jobs','auto_commands'];foreach($tables as $t){try{$pdo->query('SELECT 1 FROM `'.$t.'` LIMIT 1');$check(true,'Tabela: '.$t);}catch(Throwable){$check(false,'Tabela ausente: '.$t);}}foreach(['owner','reception','professional'] as $r){$q=$pdo->prepare('SELECT COUNT(*) FROM roles WHERE slug=:s');$q->execute(['s'=>$r]);$check((int)$q->fetchColumn()>0,'Perfil: '.$r);} $check((int)$pdo->query('SELECT COUNT(*) FROM plans WHERE active=1')->fetchColumn()>0,'Existe plano ativo');$q=$pdo->prepare("SELECT COUNT(*) FROM tenants WHERE slug='auto-prime-demonstracao'");$q->execute();if((int)$q->fetchColumn()>0)$warn[]='Empresa Auto Demo já existe; o instalador preservará os dados existentes.';}catch(Throwable $e){$fail[]='Banco indisponível: '.$e->getMessage();}
$index=@file_get_contents($root.'/index.php')?:'';$check(str_contains($index,"/auto/{slug}"),'Rota pública Auto disponível');
foreach($ok as $m)echo '[OK] '.$m.PHP_EOL;foreach($warn as $m)echo '[AVISO] '.$m.PHP_EOL;if($fail){foreach($fail as $m)echo '[FALHA] '.$m.PHP_EOL;fwrite(STDERR,'PRE-FLIGHT: FALHOU. Nenhuma alteração foi feita.'.PHP_EOL);exit(1);}echo 'PRE-FLIGHT: OK. Nenhuma alteração foi feita.'.PHP_EOL;
