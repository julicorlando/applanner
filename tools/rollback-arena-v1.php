<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
$root=dirname(__DIR__);$base=$root.'/storage/update-backups';
$requested=$argv[1]??'';
if($requested!==''){$backup=rtrim($requested,'/');if(!str_starts_with($backup,'/'))$backup=$base.'/'.$backup;}
else{$dirs=glob($base.'/arena-v1-*',GLOB_ONLYDIR)?:[];rsort($dirs,SORT_STRING);$backup=$dirs[0]??'';}
if($backup===''||!is_file($backup.'/manifest.json')){fwrite(STDERR,"Backup Arena V1 não encontrado.\n");exit(1);}
$manifest=json_decode((string)file_get_contents($backup.'/manifest.json'),true);if(!is_array($manifest)){fwrite(STDERR,"Manifesto inválido.\n");exit(1);}
foreach(array_reverse($manifest['files']??[]) as $entry){$rel=(string)$entry['path'];$dest=$root.'/'.$rel;if(!empty($entry['existed'])){$src=$backup.'/files/'.$rel;if(!is_file($src)){fwrite(STDERR,"Backup ausente: {$rel}\n");exit(1);}if(!is_dir(dirname($dest)))mkdir(dirname($dest),0755,true);copy($src,$dest);}elseif(is_file($dest)){unlink($dest);}}
echo "[OK] Arquivos restaurados de {$backup}\n";
echo "As tabelas/dados incrementais da Arena foram mantidos intencionalmente. O código anterior simplesmente os ignora.\n";
