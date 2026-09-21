<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$id=$argv[1]??'';
if(!preg_match('/^ERR-\d{8}-[A-F0-9]{6}$/',$id)){fwrite(STDERR,"Uso: php diagnose-error.php ERR-AAAAMMDD-XXXXXX\n");exit(2);}
$file=__DIR__.'/storage/logs/app.log';if(!is_file($file)){fwrite(STDERR,"app.log não encontrado em storage/logs/.\n");exit(1);}
$lines=file($file,FILE_IGNORE_NEW_LINES);$hits=[];$capture=false;$block=[];
foreach($lines as $line){if(str_contains($line,$id)){if($block)$hits[]=$block;$block=[$line];$capture=true;continue;}if($capture){if(preg_match('/^\[[^\]]+\]\s+ERR-\d{8}-[A-F0-9]{6}/',$line)){if($block)$hits[]=$block;$block=[];$capture=false;}elseif(count($block)<30)$block[]=$line;}}
if($block)$hits[]=$block;if(!$hits){fwrite(STDERR,"Código {$id} não encontrado no app.log deste servidor.\n");exit(1);}foreach($hits as $i=>$b){echo "===== ocorrência ".($i+1)." =====\n".implode("\n",$b)."\n\n";}exit(0);
