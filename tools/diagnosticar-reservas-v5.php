<?php
declare(strict_types=1);
require dirname(__DIR__) . '/app/Core/bootstrap.php';
use App\Core\Database;
$pdo = Database::connection();
$ok = true;
function check(bool $pass, string $label, string $detail=''): void { global $ok; echo ($pass ? '[OK] ' : '[FALHA] ') . $label . ($detail!=='' ? ' — '.$detail : '') . PHP_EOL; if(!$pass)$ok=false; }
foreach (['sports_settings','sports_modalities','sports_courts','sports_court_modalities','sports_court_hours','sports_price_rules','sports_court_blocks','sports_reservations','sports_reservation_history'] as $table) {
    try { $q=$pdo->query("SHOW TABLES LIKE ".$pdo->quote($table)); check((bool)$q->fetchColumn(), 'Tabela '.$table); } catch(Throwable $e){ check(false,'Tabela '.$table,$e->getMessage()); }
}
try {
    $q=$pdo->query("SELECT COUNT(*) FROM sports_reservations r INNER JOIN sports_courts c ON c.id=r.court_id AND c.tenant_id=r.tenant_id LEFT JOIN sports_modalities m ON m.id=r.modality_id AND m.tenant_id=r.tenant_id");
    check(true,'Consulta principal de reservas','registros='.$q->fetchColumn());
} catch(Throwable $e){ check(false,'Consulta principal de reservas',$e->getMessage()); }
foreach (['sports.view','sports.manage','sports.reservations.manage'] as $slug) {
    try { $q=$pdo->prepare('SELECT COUNT(*) FROM permissions WHERE slug=:slug');$q->execute(['slug'=>$slug]);check((int)$q->fetchColumn()>0,'Permissão '.$slug); } catch(Throwable $e){ check(false,'Permissão '.$slug,$e->getMessage()); }
}
$files=['app/Controllers/SportsReservationsController.php','app/Views/sports/reservations.php'];
foreach($files as $f){check(is_file(dirname(__DIR__).'/'.$f),'Arquivo '.$f);}
exit($ok?0:1);
