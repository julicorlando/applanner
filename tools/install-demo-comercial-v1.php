<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);$dry=in_array('--dry-run',$argv,true);$payload=$root.'/patches/applanner-demo-comercial-v1/payload';
function runCmd(string $cmd):string{$out=[];$code=0;exec($cmd.' 2>&1',$out,$code);$text=implode(PHP_EOL,$out);if($code!==0)throw new RuntimeException($text?:'Comando falhou: '.$cmd);return$text;}
try{
 echo runCmd(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tools/preflight-demo-comercial-v1.php')).PHP_EOL;
 if($dry){echo 'DRY RUN: OK. Nenhuma alteração foi feita. Execute sem --dry-run para instalar.'.PHP_EOL;exit;}
 $stamp=date('Ymd-His');$backup=$root.'/storage/update-backups/demo-comercial-v1-'.$stamp;if(!is_dir($backup)&&!mkdir($backup,0775,true)&&!is_dir($backup))throw new RuntimeException('Não foi possível criar backup.');
 $files=['app/Views/commercial/landing.php','public/assets/css/index-conversion.css','public/assets/js/index-conversion.js','tools/demo-auto-company.php','tests/demo_commercial_smoke.php'];
 $backed=[];foreach(array_merge($files,['app/Views/layout.php']) as $rel){$src=$root.'/'.$rel;if(is_file($src)){$dst=$backup.'/'.$rel;if(!is_dir(dirname($dst)))mkdir(dirname($dst),0775,true);if(!copy($src,$dst))throw new RuntimeException('Falha no backup de '.$rel);$backed[]=$rel;}}
 foreach($files as $rel){$src=$payload.'/'.$rel;$dst=$root.'/'.$rel;if(!is_dir(dirname($dst)))mkdir(dirname($dst),0775,true);if(!copy($src,$dst))throw new RuntimeException('Falha ao copiar '.$rel);}
 // Força cache bust apenas do CSS da landing, preservando o restante do layout instalado.
 $layoutPath=$root.'/app/Views/layout.php';$layout=file_get_contents($layoutPath);if($layout===false)throw new RuntimeException('Não foi possível ler layout.php.');$layout=preg_replace('#index-conversion\.css\?v=[^"\']+#','index-conversion.css?v=20260818-showcase',$layout,1);if($layout===null||file_put_contents($layoutPath,$layout)===false)throw new RuntimeException('Falha ao atualizar versão do CSS.');
 foreach(['app/Views/commercial/landing.php','tools/demo-auto-company.php','tests/demo_commercial_smoke.php','app/Views/layout.php'] as $rel)echo runCmd(escapeshellarg(PHP_BINARY).' -l '.escapeshellarg($root.'/'.$rel)).PHP_EOL;
 $demoOutput=runCmd(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tools/demo-auto-company.php').' install');echo PHP_EOL.$demoOutput.PHP_EOL;
 echo PHP_EOL.runCmd(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tests/demo_commercial_smoke.php')).PHP_EOL;
 file_put_contents($backup.'/BACKUP_MANIFEST.txt',implode(PHP_EOL,$backed).PHP_EOL);
 echo PHP_EOL.'PATCH DEMO COMERCIAL V1 INSTALADO.'.PHP_EOL.'Backup dos arquivos: '.$backup.PHP_EOL.'Index: /'.PHP_EOL.'Demo pública: /auto/applanner-auto-demo'.PHP_EOL;
}catch(Throwable $e){fwrite(STDERR,'[ERRO] '.$e->getMessage().PHP_EOL);exit(1);}
