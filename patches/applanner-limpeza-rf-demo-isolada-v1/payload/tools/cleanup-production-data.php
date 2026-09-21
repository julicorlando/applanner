<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
require $root.'/app/Core/bootstrap.php';

use App\Core\Database;

$pdo=Database::connection();
$apply=in_array('--apply',$argv,true);
$keepSlug=null;
foreach($argv as $arg) if(str_starts_with($arg,'--keep-slug=')) $keepSlug=trim(substr($arg,12));

function fail(string $m):never{fwrite(STDERR,"[ERRO] {$m}\n");exit(1);}
function tableHas(PDO $pdo,string $table,string $column):bool{
    $db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
    $q=$pdo->prepare("SELECT 1 FROM information_schema.columns WHERE table_schema=:db AND table_name=:t AND column_name=:c LIMIT 1");
    $q->execute(['db'=>$db,'t'=>$table,'c'=>$column]);return(bool)$q->fetchColumn();
}
function qname(string $v):string{return '`'.str_replace('`','``',$v).'`';}
function normalizeName(string $s):string{
    $a=iconv('UTF-8','ASCII//TRANSLIT//IGNORE',$s)?:$s;
    $a=mb_strtolower($a);$a=preg_replace('/[^a-z0-9]+/',' ', $a)??$a;
    return trim(preg_replace('/\s+/',' ',$a)??$a);
}

$demoExpr=tableHas($pdo,'tenants','is_demo')?'COALESCE(is_demo,0)':'0';
$tenants=$pdo->query("SELECT id,name,slug,public_slug,status,deleted_at,{$demoExpr} is_demo FROM tenants ORDER BY id")->fetchAll(PDO::FETCH_ASSOC)?:[];
$candidates=[];
foreach($tenants as $t){
    $name=normalizeName((string)$t['name']);
    $slug=mb_strtolower((string)$t['slug']);
    $public=mb_strtolower((string)($t['public_slug']??''));
    if($keepSlug!==null){
        if($slug===mb_strtolower($keepSlug)||$public===mb_strtolower($keepSlug))$candidates[]=$t;
    }elseif($name==='rf films'||str_starts_with($slug,'rf-films')||str_starts_with($public,'rf-films'))$candidates[]=$t;
}
if(count($candidates)!==1){
    echo "Tenants encontrados:\n";
    foreach($tenants as $t)echo "  id={$t['id']} | {$t['name']} | slug={$t['slug']} | demo={$t['is_demo']}\n";
    fail('Era esperado localizar exatamente uma empresa RF Films. Use --keep-slug=SLUG se necessário.');
}
$keep=$candidates[0];$keepId=(int)$keep['id'];

$rc1At=null;
$q=$pdo->prepare("SELECT executed_at FROM migrations WHERE migration='043_applanner_rc1_production_readiness.sql' ORDER BY id DESC LIMIT 1");
$q->execute();$rc1At=$q->fetchColumn()?:null;
if(!$rc1At)fail('Migration 043 não localizada.');

$failedQ=$pdo->prepare("SELECT id,tenant_id,type,COALESCE(failed_at,updated_at,created_at) failed_when,last_error FROM jobs WHERE status='failed' AND COALESCE(failed_at,updated_at,created_at)<:rc1 ORDER BY id");
$failedQ->execute(['rc1'=>$rc1At]);$historicalFailed=$failedQ->fetchAll(PDO::FETCH_ASSOC)?:[];

$removeTenants=array_values(array_filter($tenants,fn($t)=>(int)$t['id']!==$keepId));

echo "APPLANNER - LIMPEZA CONTROLADA\n";
echo "==============================\n";
echo "PRESERVAR: tenant={$keepId} | {$keep['name']} | slug={$keep['slug']}\n";
echo "Tenants a remover: ".count($removeTenants)."\n";
foreach($removeTenants as $t)echo "  REMOVER id={$t['id']} | {$t['name']} | slug={$t['slug']} | demo={$t['is_demo']}\n";
echo "Jobs históricos failed pré-RC1: ".count($historicalFailed)."\n";
foreach($historicalFailed as $j)echo "  job={$j['id']} tenant=".($j['tenant_id']??'-')." type={$j['type']} when={$j['failed_when']}\n";
echo "Usuários globais/Master (tenant_id NULL) serão preservados.\n";
echo "Todos os dados tenant-scoped fora da RF Films serão removidos.\n";

if(!$apply){
    echo "\nDRY RUN: nenhuma alteração foi realizada.\n";
    echo "Para aplicar: php tools/cleanup-production-data.php --apply\n";
    exit(0);
}

if(count($historicalFailed)!==6){
    fail('Por segurança, a limpeza esperava exatamente 6 jobs históricos failed pré-RC1, mas encontrou '.count($historicalFailed).'. Nenhum dado foi apagado.');
}

$db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();

// Snapshot RF antes da limpeza: todas as tabelas com tenant_id.
$tc=$pdo->prepare("SELECT table_name FROM information_schema.columns WHERE table_schema=:db AND column_name='tenant_id' ORDER BY table_name");
$tc->execute(['db'=>$db]);$tenantTables=$tc->fetchAll(PDO::FETCH_COLUMN)?:[];
$baseline=[];
foreach($tenantTables as $table){
    try{
        $q=$pdo->prepare("SELECT COUNT(*) FROM ".qname($table)." WHERE tenant_id=:t");
        $q->execute(['t'=>$keepId]);$baseline[$table]=(int)$q->fetchColumn();
    }catch(Throwable){}
}

// Manifesto antes da exclusão.
$manifestDir=$root.'/storage/private/cleanup-manifests';
if(!is_dir($manifestDir)&&!mkdir($manifestDir,0750,true)&&!is_dir($manifestDir))fail('Não foi possível criar pasta de manifesto.');
$manifest=$manifestDir.'/cleanup-rf-'.date('Ymd-His').'.json';
file_put_contents($manifest,json_encode([
    'created_at'=>date(DATE_ATOM),
    'keep_tenant'=>$keep,
    'remove_tenants'=>$removeTenants,
    'historical_failed_jobs'=>$historicalFailed,
    'rf_baseline'=>$baseline,
],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES),LOCK_EX);
@chmod($manifest,0640);

$pdo->beginTransaction();
try{
    $pdo->exec('SET FOREIGN_KEY_CHECKS=0');

    // 1) Remove dados diretamente tenant-scoped fora da RF Films.
    foreach($tenantTables as $table){
        if($table==='users'){
            // Preserva usuários globais da plataforma/Master (tenant_id NULL).
            $sql="DELETE FROM ".qname($table)." WHERE tenant_id IS NOT NULL AND tenant_id<>:keep";
        }else{
            $sql="DELETE FROM ".qname($table)." WHERE tenant_id IS NOT NULL AND tenant_id<>:keep";
        }
        $q=$pdo->prepare($sql);$q->execute(['keep'=>$keepId]);
    }

    // 2) Tabelas que referenciam tenants por outro nome (ex.: converted_tenant_id).
    $fk=$pdo->prepare("
      SELECT k.table_name,k.column_name
      FROM information_schema.key_column_usage k
      WHERE k.table_schema=:db AND k.referenced_table_schema=:db2
        AND k.referenced_table_name='tenants'
        AND k.column_name<>'tenant_id'
    ");
    $fk->execute(['db'=>$db,'db2'=>$db]);
    foreach($fk->fetchAll(PDO::FETCH_ASSOC) as $r){
        $table=$r['table_name'];$col=$r['column_name'];
        if(tableHas($pdo,$table,'tenant_id')) continue; // RF-owned rows are protected by tenant_id.
        $sql="DELETE FROM ".qname($table)." WHERE ".qname($col)." IS NOT NULL AND ".qname($col)."<>:keep";
        $q=$pdo->prepare($sql);$q->execute(['keep'=>$keepId]);
    }

    // 3) Remove tenants, mantendo apenas RF Films.
    $q=$pdo->prepare("DELETE FROM tenants WHERE id<>:keep");$q->execute(['keep'=>$keepId]);

    // 4) Remove explicitamente os 6 jobs históricos dos testes.
    $ids=array_map(fn($r)=>(int)$r['id'],$historicalFailed);
    if($ids){
        $marks=implode(',',array_fill(0,count($ids),'?'));
        $pdo->prepare("DELETE FROM jobs WHERE id IN ($marks)")->execute($ids);
    }

    // 5) Limpa órfãos criados por tabelas auxiliares sem tenant_id.
    // Nunca exclui linha com tenant_id=RF.
    $fks=$pdo->prepare("
      SELECT k.table_name,k.column_name,k.referenced_table_name,k.referenced_column_name
      FROM information_schema.key_column_usage k
      WHERE k.table_schema=:db AND k.referenced_table_schema=:db2 AND k.referenced_table_name IS NOT NULL
      ORDER BY k.table_name,k.constraint_name,k.ordinal_position
    ");
    $fks->execute(['db'=>$db,'db2'=>$db]);$fkRows=$fks->fetchAll(PDO::FETCH_ASSOC)?:[];
    for($round=0;$round<8;$round++){
        $removed=0;
        foreach($fkRows as $r){
            $ct=$r['table_name'];$cc=$r['column_name'];$pt=$r['referenced_table_name'];$pc=$r['referenced_column_name'];
            if($ct===$pt) continue;
            $guard=tableHas($pdo,$ct,'tenant_id')?" AND (c.tenant_id IS NULL OR c.tenant_id<>".(int)$keepId.")":"";
            $sql="DELETE c FROM ".qname($ct)." c LEFT JOIN ".qname($pt)." p ON c.".qname($cc)."=p.".qname($pc)
                ." WHERE c.".qname($cc)." IS NOT NULL AND p.".qname($pc)." IS NULL".$guard;
            try{$n=$pdo->exec($sql);$removed+=(int)$n;}catch(Throwable){}
        }
        if($removed===0)break;
    }

    // 6) RF Films deve permanecer bit-a-bit em volume por tenant_id.
    foreach($baseline as $table=>$before){
        $q=$pdo->prepare("SELECT COUNT(*) FROM ".qname($table)." WHERE tenant_id=:t");
        $q->execute(['t'=>$keepId]);$after=(int)$q->fetchColumn();
        if($after!==$before)throw new RuntimeException("Proteção RF falhou em {$table}: antes={$before}, depois={$after}");
    }

    if((int)$pdo->query("SELECT COUNT(*) FROM tenants")->fetchColumn()!==1)throw new RuntimeException('Após limpeza deveria existir somente RF Films antes da recriação da demo.');
    $remainingFailed=(int)$pdo->query("SELECT COUNT(*) FROM jobs WHERE status='failed'")->fetchColumn();
    if($remainingFailed!==0)throw new RuntimeException("Ainda existem {$remainingFailed} job(s) failed.");

    $pdo->exec('SET FOREIGN_KEY_CHECKS=1');
    $pdo->commit();

    // Aceites anteriores eram de testes; homologação deve recomeçar limpa.
    @unlink($root.'/storage/private/rc1-acceptance.json');

    echo "\n[OK] Limpeza concluída.\n";
    echo "[OK] RF Films preservada e validada em ".count($baseline)." tabela(s) tenant-scoped.\n";
    echo "[OK] 6 jobs históricos de teste removidos.\n";
    echo "[OK] Aceites RC1 antigos removidos para nova homologação.\n";
    echo "Manifesto: {$manifest}\n";
}catch(Throwable $e){
    if($pdo->inTransaction())$pdo->rollBack();
    try{$pdo->exec('SET FOREIGN_KEY_CHECKS=1');}catch(Throwable){}
    fail('Limpeza cancelada/rollback: '.$e->getMessage());
}
