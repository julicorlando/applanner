<?php
$root=dirname(__DIR__);
$routes=file_get_contents($root.'/index.php');
$layout=file_get_contents($root.'/app/Views/layout.php');
$billing=file_get_contents($root.'/app/Controllers/BillingController.php');
$support=file_get_contents($root.'/app/Controllers/SupportController.php');
$professional=file_get_contents($root.'/app/Controllers/ProfessionalController.php');
$public=file_get_contents($root.'/app/Controllers/PublicBookingController.php');
$master=file_get_contents($root.'/app/Controllers/MasterController.php');
$automation=file_get_contents($root.'/cron/automation_dispatch.php');
$migration=file_get_contents($root.'/database/migrations/013_operational_modules.sql');
$checks=[
 'MENU-001'=>str_contains($layout,"modules['products']")&&str_contains($layout,"modules['finance']")&&str_contains($layout,"modules['behavior']"),
 'MENU-002'=>!str_contains($layout,"['Integrações','/settings")&&str_contains($layout,"['Integrações','/master/integrations']"),
 'PROF-LOGIN-001'=>str_contains($routes,"'/profissional/login'")&&is_file($root.'/app/Views/auth/professional-login.php'),
 'PROF-EDIT-001'=>str_contains($routes,"'/professionals/{id}/edit'")&&str_contains($routes,"'/professionals/{id}/delete'"),
 'PROF-AVAIL-001'=>str_contains($routes,"'/professional/availability'")&&str_contains($professional,'professional_availability'),
 'PUBLIC-PROF-001'=>str_contains($routes,"'/a/{slug}/p/{professional}'")&&str_contains($public,'public function professional'),
 'PUBLIC-SLOTS-001'=>str_contains($routes,"'/a/{slug}/availability'")&&str_contains($public,'AvailabilityService')&&is_file($root.'/app/Services/AvailabilityService.php'),
 'UPGRADE-001'=>str_contains($routes,"'/billing/plans'")&&str_contains($billing,'assertUpgrade'),
 'PAYMENT-001'=>str_contains($billing,'new MercadoPagoProvider')&&!str_contains($billing,'new SandboxPaymentProvider'),
 'SUPPORT-001'=>str_contains($routes,"'/support/{id}/start-access'")&&str_contains($support,'SUPPORT_ACCESS_STARTED'),
 'MASTER-PLAN-001'=>str_contains($routes,"'/master/plans/create'")&&str_contains($routes,"'/master/plans/{id}/edit'")&&str_contains($master,'savePlan'),
 'MASTER-USERS-001'=>str_contains($routes,"'/master/users/{id}/edit'")&&str_contains($master,'blockUser'),
 'MASTER-AUDIT-001'=>str_contains($routes,"'/master/login-audit'"),
 'AUTOMATION-001'=>str_contains($automation,"t.status IN('trial','active')")&&str_contains($automation,"status='completed'")&&str_contains($automation,'consent_marketing=1'),
 'MULTIUNIT-001'=>str_contains($routes,"'/units'")&&str_contains($migration,"'units.view'"),
 'CLINICAL-001'=>str_contains($routes,"'/clinical'")&&str_contains($migration,'medical_record_entries')&&str_contains($migration,"medical_records.view"),
 'PHANTOM-MODULES-001'=>str_contains($migration,"UPDATE modules SET active=0 WHERE slug IN('whatsapp','odontology','api')"),
 'LEGACY-BANK-001'=>!str_contains($routes,"'/master/bank-accounts'"),
];
$failed=0;foreach($checks as $id=>$ok){echo $id.' '.($ok?'PASS':'FAIL').PHP_EOL;if(!$ok)$failed++;}exit($failed?1:0);
