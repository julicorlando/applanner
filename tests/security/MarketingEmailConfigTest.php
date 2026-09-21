<?php
$root=dirname(__DIR__,2);
$integration=file_get_contents($root.'/app/Controllers/IntegrationController.php');
$worker=file_get_contents($root.'/cron/worker.php');
$setting=file_get_contents($root.'/app/Services/PlatformSetting.php');
$encrypted=str_contains($integration,"platform.marketing_email")&&str_contains($integration,'setSecret');
$masked=!str_contains($integration,"'email'=>Encryption::decrypt")&&!str_contains($integration,"'password'=>PlatformSetting::secret");
$workerGlobal=str_contains($worker,"PlatformSetting::secret")&&str_contains($worker,"platform.marketing_email");
$dedup=str_contains($setting,'ORDER BY id DESC FOR UPDATE')&&str_contains($setting,'DELETE FROM settings WHERE id IN');
$legacyGone=!is_file($root.'/app/Controllers/MarketingEmailController.php')&&!is_file($root.'/app/Controllers/CampaignController.php');
$ok=$encrypted&&$masked&&$workerGlobal&&$dedup&&$legacyGone;
echo ($ok?'PASS':'FAIL')." Master marketing sender encrypted, centralizado, deduplicated e worker fallback\n";exit($ok?0:1);
