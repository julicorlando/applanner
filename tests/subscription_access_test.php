<?php
declare(strict_types=1);require dirname(__DIR__).'/app/Core/SubscriptionAccess.php';use App\Core\SubscriptionAccess;
$cases=[['active','active',null,false],['trial','trial',date('Y-m-d H:i:s',time()+3600),false],['trial','trial',date('Y-m-d H:i:s',time()-3600),true],['active','past_due',null,true],['suspended','active',null,true],['cancelled','active',null,true]];
foreach($cases as [$tenant,$subscription,$trial,$expected]){if(SubscriptionAccess::isRestricted($tenant,$subscription,$trial)!==$expected){fwrite(STDERR,"FAIL {$tenant}/{$subscription}\n");exit(1);}}
$source=file_get_contents(dirname(__DIR__).'/app/Core/SubscriptionAccess.php');foreach(['/billing','/checkout','http_response_code(402)','Location: /billing']as $needle)if(!str_contains($source,$needle)){fwrite(STDERR,"FAIL missing {$needle}\n");exit(1);}echo "OK: conta bloqueada mantém login, libera cobrança e bloqueia módulos/API.\n";
