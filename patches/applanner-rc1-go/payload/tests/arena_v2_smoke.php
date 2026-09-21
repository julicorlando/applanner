<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
spl_autoload_register(static function(string $class) use($root):void{$prefix='App\\';if(!str_starts_with($class,$prefix))return;$f=$root.'/app/'.str_replace('\\','/',substr($class,strlen($prefix))).'.php';if(is_file($f))require_once $f;});
try{
  $pdo=\App\Core\Database::connection();
  $db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
  $mustMigrate=['037_applanner_arena_v1.sql','038_applanner_arena_v2_complete.sql'];
  $applied=$pdo->query("SELECT migration FROM migrations WHERE migration IN ('037_applanner_arena_v1.sql','038_applanner_arena_v2_complete.sql')")->fetchAll(PDO::FETCH_COLUMN);
  foreach($mustMigrate as $m)if(!in_array($m,$applied,true))throw new RuntimeException('Migration não registrada: '.$m);
  $tables=['sports_arena_settings','sports_reservations','sports_waitlist','sports_classes','sports_class_makeups','sports_class_billing_log','sports_tournaments','sports_tournament_matches','sports_tournament_events','sports_commands','sports_dynamic_pricing_audit','tenant_payment_transactions'];
  $st=$pdo->prepare('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=? AND TABLE_NAME=?');
  foreach($tables as $t){$st->execute([$db,$t]);if((int)$st->fetchColumn()!==1)throw new RuntimeException('Tabela ausente: '.$t);}
  $columns=[
    'sports_arena_settings'=>['dynamic_pricing_enabled','dynamic_last_minute_discount_percent','dynamic_high_occupancy_surcharge_percent','waitlist_email_enabled'],
    'sports_reservations'=>['base_total_amount','pricing_multiplier','pricing_details_json','tournament_match_id'],
    'sports_waitlist'=>['notify_email','notify_whatsapp','offered_starts_at','offered_total'],
    'sports_tournament_matches'=>['round_number','reservation_id']
  ];
  $cs=$pdo->prepare('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME=?');
  foreach($columns as $t=>$need){$cs->execute([$db,$t]);$have=array_flip($cs->fetchAll(PDO::FETCH_COLUMN));foreach($need as $c)if(!isset($have[$c]))throw new RuntimeException("Coluna ausente: {$t}.{$c}");}
  $rs=$pdo->prepare('SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME=? AND COLUMN_NAME=?');
  $rs->execute([$db,'sports_reservations','professional_id']); if((int)$rs->fetchColumn()>0)throw new RuntimeException('sports_reservations não deve depender de professional_id.');
  $index=(string)file_get_contents($root.'/index.php');
  foreach(['/arena/reserva/{token}/card-payment','/sports/commands/open','/sports/classes/{id}/attendance','/sports/tournaments/{id}/advance'] as $r)if(!str_contains($index,$r))throw new RuntimeException('Rota ausente: '.$r);
  foreach(['app/Services/ArenaDynamicPricingService.php','app/Services/ArenaTournamentService.php','public/assets/js/arena-card-payment.js'] as $f)if(!is_file($root.'/'.$f))throw new RuntimeException('Arquivo ausente: '.$f);
  echo "[OK] Migration 037/038\n[OK] Schema Arena V2\n[OK] Reserva sem profissional\n[OK] Rotas críticas\n[OK] Preço dinâmico, torneios e cartão presentes\nARENA V2 SMOKE: OK\n";
}catch(Throwable $e){fwrite(STDERR,'ARENA V2 SMOKE: FALHOU — '.$e->getMessage()."\n");exit(1);}
