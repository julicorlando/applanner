<?php
$root=dirname(__DIR__,2);
$code=file_get_contents($root.'/app/Controllers/AppointmentController.php');
$checks=[
    'agenda list scoped'=>str_contains($code,'WHERE a.tenant_id=:t AND (:p IS NULL OR a.professional_id=:p2)'),
    'professional forced on create'=>str_contains($code,'$bound=$this->professionalId($t);if($bound!==null)$professional=$bound'),
    'status scoped'=>str_contains($code,'$bound=$this->professionalId($t)') && str_contains($code,'professional_id'),
    'binding tenant scoped'=>str_contains($code,'SELECT id FROM professionals WHERE tenant_id=:t AND user_id=:u AND active=1'),
];
$failed=false;foreach($checks as $name=>$ok){echo ($ok?'PASS ':'FAIL ').$name.PHP_EOL;if(!$ok)$failed=true;}exit($failed?1:0);
