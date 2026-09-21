<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);require $root.'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();
echo "APPLANNER - PRE-FLIGHT LIMPEZA RF / DEMO ISOLADA\n";
echo "=================================================\n";
foreach(['tenants','users','roles','jobs','migrations','backups','backup_verifications'] as $t){try{$pdo->query("SELECT 1 FROM `$t` LIMIT 1");echo "[OK] {$t}\n";}catch(Throwable $e){fwrite(STDERR,"[ERRO] tabela {$t}: {$e->getMessage()}\n");exit(1);}}
$q=$pdo->query("SELECT id,name,slug,public_slug FROM tenants ORDER BY id");$rows=$q->fetchAll()?:[];
$c=[];foreach($rows as $t){$x=mb_strtolower((string)$t['name']);if((str_contains($x,'rf')&&str_contains($x,'films'))||str_starts_with(mb_strtolower((string)$t['slug']),'rf-films'))$c[]=$t;}
if(count($c)!==1){echo "Tenants:\n";foreach($rows as $t)echo "  {$t['id']} | {$t['name']} | {$t['slug']}\n";fwrite(STDERR,"[ERRO] RF Films não foi identificada de forma única.\n");exit(1);}
$failed=(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='failed'")->fetchColumn();
echo "[OK] RF Films: id={$c[0]['id']} | {$c[0]['name']} | {$c[0]['slug']}\n";
echo "[INFO] tenants atuais: ".count($rows)."\n";
echo "[INFO] jobs failed atuais: {$failed}\n";
echo "PRE-FLIGHT: OK. Nenhuma alteração foi feita.\n";
