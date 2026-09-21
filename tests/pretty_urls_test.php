<?php
declare(strict_types=1);
$root=dirname(__DIR__);$htaccess=file_get_contents($root.'/.htaccess');$fail=[];
foreach(['Options -Indexes -MultiViews','THE_REQUEST','install/index\\.php','RewriteRule ^ - [F,L]','app|config|cron|database|storage|tests'] as $needle)if(!str_contains($htaccess,$needle))$fail[]=$needle;
$iterator=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root.'/app/Views',FilesystemIterator::SKIP_DOTS));
foreach($iterator as $file){if($file->getExtension()!=='php')continue;$source=file_get_contents($file->getPathname());if(preg_match('/(?:href|action)=["\'][^"\']*\.php/i',$source))$fail[]='URL .php em '.$file->getFilename();}
if($fail){fwrite(STDERR,"FAIL URLs amigáveis:\n- ".implode("\n- ",$fail)."\n");exit(1);}echo "OK: URLs sem .php e acesso direto a scripts bloqueado.\n";
