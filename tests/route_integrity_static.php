<?php
declare(strict_types=1);
$root=dirname(__DIR__);$index=file_get_contents($root.'/index.php');$missing=[];
preg_match_all('/\$router->(?:get|post|put|patch|delete)\(\s*[\'"]([^\'"]+)[\'"]\s*,\s*\[([A-Za-z0-9_]+)::class\s*,\s*[\'"]([A-Za-z0-9_]+)[\'"]\]\s*\)/',$index,$matches,PREG_SET_ORDER);
foreach($matches as $m){[$all,$route,$controller,$method]=$m;$file=$root.'/app/Controllers/'.$controller.'.php';if(!is_file($file)){$missing[]="$route -> $controller (controller ausente)";continue;}$code=file_get_contents($file);if(!preg_match('/public\\s+function\\s+'.preg_quote($method,'/').'\\s*\\(/',$code))$missing[]="$route -> $controller::$method (método ausente)";}
if($missing){fwrite(STDERR,"Rotas inválidas:\n- ".implode("\n- ",$missing)."\n");exit(1);}echo 'PASS route integrity: '.count($matches)." rotas apontam para métodos existentes.\n";
