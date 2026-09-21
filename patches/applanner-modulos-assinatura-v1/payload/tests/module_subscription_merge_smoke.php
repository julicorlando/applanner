<?php
declare(strict_types=1);
$root=dirname(__DIR__);$errors=[];$need=[
 'app/Services/SubscriptionModuleService.php',
 'app/Services/MercadoPagoProvider.php',
 'app/Controllers/ModuleController.php',
 'app/Controllers/BillingController.php',
 'app/Views/billing/modules.php',
 'app/Views/master/module-requests.php',
 'database/migrations/039_modules_merged_subscription.sql'
];
foreach($need as $f)if(!is_file($root.'/'.$f))$errors[]='Arquivo ausente: '.$f;
$checks=[
 'app/Services/MercadoPagoProvider.php'=>['updateSubscriptionAmount','/preapproval/'],
 'app/Services/SubscriptionModuleService.php'=>['merged_subscription','activateApprovedRequest','addon_contracted_price'],
 'app/Controllers/ModuleController.php'=>['activateApprovedRequest','MODULE_MERGED_INTO_SUBSCRIPTION'],
 'app/Controllers/BillingController.php'=>['augmentQuote','addon_total'],
 'app/Views/billing/modules.php'=>['Incorporar à assinatura','sem criar uma segunda assinatura'],
 'database/migrations/039_modules_merged_subscription.sql'=>['subscription_module_adjustments','billing_mode','base_contracted_price']
];
foreach($checks as $f=>$tokens){$s=(string)@file_get_contents($root.'/'.$f);foreach($tokens as $token)if(!str_contains($s,$token))$errors[]=$f.' sem marcador '.$token;}
if($errors){fwrite(STDERR,"module subscription merge smoke: FALHOU\n- ".implode("\n- ",$errors)."\n");exit(1);}echo "module subscription merge smoke: OK\n";
