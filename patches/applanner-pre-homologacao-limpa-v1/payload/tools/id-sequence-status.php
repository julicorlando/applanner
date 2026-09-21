<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Core\Database;
$pdo=Database::connection();$db=(string)$pdo->query('SELECT DATABASE()')->fetchColumn();
$q=$pdo->prepare("SELECT table_name,column_name,auto_increment FROM information_schema.columns c JOIN information_schema.tables t ON t.table_schema=c.table_schema AND t.table_name=c.table_name WHERE c.table_schema=:d AND c.extra LIKE '%auto_increment%' ORDER BY c.table_name");
$q->execute(['d'=>$db]);$rows=$q->fetchAll(PDO::FETCH_ASSOC)?:[];
foreach($rows as $r){
 $t=str_replace('`','``',$r['table_name']);$c=str_replace('`','``',$r['column_name']);
 $max=(int)$pdo->query("SELECT COALESCE(MAX(`{$c}`),0) FROM `{$t}`")->fetchColumn();
 $expected=$max>0?$max+1:1;
 echo "{$r['table_name']} | max={$max} | next=".($r['auto_increment']??'NULL')." | expected={$expected}\n";
}
