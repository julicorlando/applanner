<?php
$root=dirname(__DIR__);$checks=[
 'BACKUP-SERVICE'=>is_file($root.'/app/Services/BackupService.php'),
 'BACKUP-CONTROLLER'=>is_file($root.'/app/Controllers/BackupController.php'),
 'BACKUP-VIEW'=>is_file($root.'/app/Views/master/backups.php'),
 'BACKUP-ROUTES'=>str_contains(file_get_contents($root.'/index.php'),"/master/backups"),
 'BACKUP-CSRF'=>str_contains(file_get_contents($root.'/app/Controllers/BackupController.php'),'CSRF::enforce()'),
 'BACKUP-PRIVATE-DOWNLOAD'=>str_contains(file_get_contents($root.'/app/Controllers/BackupController.php'),'realpath')&&str_contains(file_get_contents($root.'/app/Controllers/BackupController.php'),'str_starts_with'),
 'COMMERCIAL-HERO'=>str_contains(file_get_contents($root.'/app/Views/commercial/landing.php'),'sales-hero'),
 'COMMERCIAL-PLANS'=>str_contains(file_get_contents($root.'/app/Views/commercial/plans-grid.php'),'sales-price-card'),
];$failed=array_keys(array_filter($checks,fn($ok)=>!$ok));if($failed){fwrite(STDERR,'FAIL '.implode(', ',$failed)."\n");exit(1);}echo 'PASS V4.1 backup and commercial presentation'."\n";
