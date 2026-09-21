<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=rtrim((string)(getenv('APPLANNER_ROOT') ?: dirname(__DIR__)),'/');if(!is_file($root.'/app/Core/bootstrap.php')){fwrite(STDERR,"[ERRO] bootstrap não encontrado em {$root}/app/Core/bootstrap.php\n");exit(1);}
require $root.'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();
echo "APPLANNER - PRE-FLIGHT LIMPEZA FINAL\n";
echo "====================================\n";
foreach(['tenants','users','jobs','backups','backup_verifications','operational_incidents','homologation_runs'] as $t){
 try{$pdo->query("SELECT 1 FROM `$t` LIMIT 1");echo "[OK] {$t}\n";}catch(Throwable $e){fwrite(STDERR,"[ERRO] {$t}: {$e->getMessage()}\n");exit(1);}
}
$real=$pdo->query("SELECT id,name,slug FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=0 ORDER BY id")->fetchAll()?:[];
$demo=$pdo->query("SELECT id,name,slug,public_slug FROM tenants WHERE deleted_at IS NULL AND COALESCE(is_demo,0)=1 ORDER BY id")->fetchAll()?:[];
if(count($real)!==1){fwrite(STDERR,"[ERRO] Esperado exatamente 1 tenant real.\n");exit(1);}
$n=mb_strtolower((string)$real[0]['name']);if(!(str_contains($n,'rf')&&str_contains($n,'films'))&&$real[0]['slug']!=='rf-films'){fwrite(STDERR,"[ERRO] Tenant real não é RF Films.\n");exit(1);}
echo "[OK] RF Films: id={$real[0]['id']} | {$real[0]['name']} | {$real[0]['slug']}\n";
echo "[INFO] demos: ".count($demo)."\n";foreach($demo as $d)echo "  REMOVER id={$d['id']} | {$d['name']} | {$d['slug']} | {$d['public_slug']}\n";
echo "[INFO] backups atuais: ".(int)$pdo->query("SELECT COUNT(*) FROM backups")->fetchColumn()."\n";
echo "[INFO] verificações atuais: ".(int)$pdo->query("SELECT COUNT(*) FROM backup_verifications")->fetchColumn()."\n";
echo "[INFO] jobs failed: ".(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='failed'")->fetchColumn()."\n";
echo "[INFO] incidentes aplicação: ".(int)$pdo->query("SELECT COUNT(*) FROM operational_incidents WHERE category='application' AND title='Erros recentes da aplicação'")->fetchColumn()."\n";
echo "PRE-FLIGHT: OK. Nenhuma alteração foi feita.\n";
