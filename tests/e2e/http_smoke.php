<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){fwrite(STDERR,"CLI only\n");exit(2);}
$base=rtrim(getenv('E2E_BASE_URL')?:'','/');if($base===''){fwrite(STDERR,"BLOCKED: defina E2E_BASE_URL com a URL HTTPS de homologação.\n");exit(3);}if(!str_starts_with($base,'https://')){fwrite(STDERR,"ABORTADO: homologação final exige HTTPS.\n");exit(4);}
function getUrl(string $url):array{$ctx=stream_context_create(['http'=>['method'=>'GET','ignore_errors'=>true,'timeout'=>12,'header'=>"User-Agent: AgendaSaaS-E2E/3.0\r\n"],'ssl'=>['verify_peer'=>true,'verify_peer_name'=>true]]);$body=@file_get_contents($url,false,$ctx);$headers=$http_response_header??[];$status=0;if(isset($headers[0])&&preg_match('/\s(\d{3})\s/',$headers[0],$m))$status=(int)$m[1];return [$status,$body===false?'':$body,$headers];}
$tests=['/' => [200,399],'/planos'=>[200,399],'/login'=>[200,399],'/profissional/login'=>[200,399],'/cadastro'=>[200,399]];$failed=[];foreach($tests as $path=>[$min,$max]){[$status,$body]=$r=getUrl($base.$path);$ok=$status>=$min&&$status<=$max&&strlen($body)>100;echo ($ok?'PASS ':'FAIL ').$path.' HTTP '.$status.PHP_EOL;if(!$ok)$failed[]=$path;}
[$status,,$headers]=getUrl($base.'/config/database.php');$protected=in_array($status,[403,404],true);echo ($protected?'PASS ':'FAIL ')."config exposure HTTP {$status}\n";if(!$protected)$failed[]='/config/database.php';
[$status]=getUrl($base.'/storage/logs/app.log');$protected=in_array($status,[403,404],true);echo ($protected?'PASS ':'FAIL ')."log exposure HTTP {$status}\n";if(!$protected)$failed[]='/storage/logs/app.log';
exit($failed?1:0);
