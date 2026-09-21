<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);$_SERVER['REQUEST_URI']='/__arena_smoke__';$_SERVER['REQUEST_METHOD']='CLI';require $root.'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();$errors=[];$ok=[];
$check=static function(bool $value,string $label)use(&$errors,&$ok):void{if($value){$ok[]=$label;}else{$errors[]=$label;}};
$q=$pdo->prepare('SELECT COUNT(*) FROM migrations WHERE migration=:m');$q->execute(['m'=>'037_applanner_arena_v1.sql']);$check((int)$q->fetchColumn()===1,'migration 037 aplicada');
foreach(['sports_settings','sports_modalities','sports_courts','sports_court_modalities','sports_court_hours','sports_price_rules','sports_price_rule_extensions','sports_court_blocks','sports_reservations','sports_reservation_history','sports_reservation_finance','sports_memberships','sports_games','sports_game_players','sports_waitlist','sports_commands','sports_command_items','sports_customer_metrics','tenant_payment_connections','tenant_payment_transactions','tenant_payment_webhook_events','sports_arena_settings'] as $table){$q=$pdo->query('SHOW TABLES LIKE '.$pdo->quote($table));$check((bool)$q->fetchColumn(),'tabela '.$table);}
$q=$pdo->query("SHOW COLUMNS FROM sports_reservations LIKE 'professional_id'");$check(!$q->fetchColumn(),'sports_reservations sem professional_id');
$q=$pdo->prepare("SELECT name FROM modules WHERE slug='sports_courts'");$q->execute();$check($q->fetchColumn()==='Arena','módulo sports_courts exibido como Arena');
foreach(['sports.agenda.view','sports.memberships.manage','sports.games.manage','sports.waitlist.manage','sports.commands.manage','sports.reports.view','banking.view','banking.manage'] as $perm){$q=$pdo->prepare('SELECT COUNT(*) FROM permissions WHERE slug=:slug');$q->execute(['slug'=>$perm]);$check((int)$q->fetchColumn()===1,'permissão '.$perm);}
$q=$pdo->query("SELECT COUNT(*) FROM modules WHERE slug='banking_integrations' AND active=1");$check((int)$q->fetchColumn()===1,'módulo Integrações Bancárias independente');
foreach($ok as $label)echo "[OK] {$label}\n";foreach($errors as $label)fwrite(STDERR,"[ERRO] {$label}\n");
if($errors){fwrite(STDERR,"\nARENA V1 SMOKE: FALHOU\n");exit(1);}echo "\nARENA V1 SMOKE: OK\n";
