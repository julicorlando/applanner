<?php
declare(strict_types=1);if(PHP_SAPI!=='cli'){http_response_code(404);exit;}require dirname(__DIR__).'/app/Core/bootstrap.php';
$backup=(new App\Services\BackupService())->create();echo "Backup concluído: {$backup['name']} ({$backup['size']} bytes)\n";
