<?php
declare(strict_types=1);
require __DIR__.'/../app/Core/bootstrap.php';
try{$ids=(new App\Services\IncidentMonitorService())->scan();echo date('c').' incident-monitor '.count($ids)." alerta(s)\n";}catch(Throwable $e){error_log('[ApPlanner Incident Monitor] '.$e->getMessage());exit(1);}
