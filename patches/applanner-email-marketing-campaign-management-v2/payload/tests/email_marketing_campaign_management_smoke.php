<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);require $root.'/app/Core/bootstrap.php';
use App\Core\Database;
$checks=[];$ok=function(string $n,bool $v)use(&$checks){$checks[]=[$n,$v];echo ($v?'[OK] ':'[FALHA] ').$n.PHP_EOL;};

$pdo=Database::connection();$cols=$pdo->query("SHOW COLUMNS FROM marketing_campaigns")->fetchAll(PDO::FETCH_COLUMN);
foreach(['image_path','image_url','image_alt','card_link_url','active','updated_at','deleted_at','source_campaign_id','resend_number'] as $col)$ok('Coluna '.$col,in_array($col,$cols,true));

$c=(string)@file_get_contents($root.'/app/Controllers/LeadMarketingController.php');
$v=(string)@file_get_contents($root.'/app/Views/master/lead-marketing.php');
$w=(string)@file_get_contents($root.'/cron/worker.php');
$i=(string)@file_get_contents($root.'/index.php');

foreach(['updateCampaign','changeCampaignReferrer','campaignStatus','redispatchCampaign','deleteCampaign'] as $m)$ok('Método '.$m,str_contains($c,'function '.$m.'('));
$ok('Reescrita de jobs pendentes',str_contains($c,'rewriteQueuedJobs'));
$ok('Cancelamento seguro de pendentes',str_contains($c,'cancelQueuedJobs'));
$ok('Proteção contra redisparo com fila',str_contains($c,'countQueuedCampaignJobs'));
$ok('Tela Redisparar',str_contains($v,'Redisparar'));
$ok('Relação de origem do redisparo',str_contains($v,'origem #'));
$ok('Worker respeita campanha inativa',str_contains($w,'Campanha inativa ou removida.'));
$ok('Worker conta skipped',str_contains($w,"SUM(status='skipped')"));

$ok('Métricas de clique',str_contains($c,'unique_clicks')&&str_contains($c,'last_click_at')&&str_contains($c,'converted_clicks'));
$ok('Detalhes de clique por contato',str_contains($c,'clickDetails')&&str_contains($v,'Cliques da campanha'));
$ok('CTR visível',str_contains($v,'únicos/enviados'));
$ok('Indicador Houve clique',str_contains($v,'Houve clique'));
$ok('Card usa link rastreado',str_contains($c,'&dest=card'));
$ok('Redirect rastreado do card',str_contains($c,"dest']??'')==='card'"));

foreach(['/campanhas/{id}/indicador','/campanhas/{id}/editar','/campanhas/{id}/status','/campanhas/{id}/redisparar','/campanhas/{id}/excluir'] as $route)$ok('Rota '.$route,str_contains($i,$route));

$bad=array_filter($checks,fn($x)=>!$x[1]);
if($bad){fwrite(STDERR,"email marketing campaign management smoke: FALHOU\n");exit(1);}
echo 'email marketing campaign management smoke: OK ('.count($checks)." verificações)\n";
