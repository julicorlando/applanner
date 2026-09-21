<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Services\{PlatformSetting,PremiumAutomationService};
$cfg=PlatformSetting::json('platform.automation');if(empty($cfg['enabled'])){echo "Automação global desativada.\n";exit;}$now=new DateTimeImmutable();if(!empty($cfg['pause_until'])){try{if(new DateTimeImmutable((string)$cfg['pause_until'])>$now){echo "Automação temporariamente pausada.\n";exit;}}catch(Throwable){}}$hour=(int)$now->format('G');$start=max(0,min(23,(int)($cfg['start_hour']??8)));$end=max(1,min(24,(int)($cfg['end_hour']??20)));if($hour<$start||$hour>=$end){echo "Fora da janela de disparos ({$start}h-{$end}h).\n";exit;}$result=(new PremiumAutomationService())->dispatch();echo "Automação premium: {$result['queued']} envio(s), {$result['customers']} cliente(s), {$result['skipped']} ignorado(s).\n";
