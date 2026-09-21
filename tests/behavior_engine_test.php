<?php
declare(strict_types=1);
require dirname(__DIR__) . '/app/Services/BehaviorEngine.php';

$result=\App\Services\BehaviorEngine::analyzeIntervals([15,14,16,15,42,14]);
if ($result['median'] < 14 || $result['median'] > 16 || in_array(42,$result['filtered_intervals'],true) || $result['confidence'] < 50) {
    fwrite(STDERR, 'BehaviorEngine não tratou o outlier corretamente: '.json_encode($result)."\n"); exit(1);
}
echo 'OK: BehaviorEngine robusto: '.json_encode($result,JSON_UNESCAPED_UNICODE)."\n";
