<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
require dirname(__DIR__).'/app/Core/bootstrap.php';
use App\Services\{BarberMaintenanceService,BarberRecurringReconciliationService};
try{$result=(new BarberMaintenanceService())->run();$result=array_merge($result,(new BarberRecurringReconciliationService())->run());echo 'Barber: '.json_encode($result,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES).PHP_EOL;}catch(Throwable $e){@file_put_contents(dirname(__DIR__).'/storage/logs/barber-cron.log','['.date('c').'] '.mb_substr($e->getMessage(),0,500).PHP_EOL,FILE_APPEND|LOCK_EX);fwrite(STDERR,'Barber erro: '.$e->getMessage().PHP_EOL);exit(1);}
