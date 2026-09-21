<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
$state=$root.'/storage/updates/arena-v2.json';
$backup=$argv[1]??'';
if($backup===''){
  if(!is_file($state)){fwrite(STDERR,"Informe o diretório de backup como primeiro argumento.\n");exit(1);}
  $j=json_decode((string)file_get_contents($state),true);$backup=(string)($j['backup_dir']??'');
}
$manifestFile=rtrim($backup,'/').'/manifest.json';
if(!is_file($manifestFile)){fwrite(STDERR,"Manifest não encontrado: {$manifestFile}\n");exit(1);}
$m=json_decode((string)file_get_contents($manifestFile),true,512,JSON_THROW_ON_ERROR);
$copy=static function(string $src,string $dst):void{$d=dirname($dst);if(!is_dir($d))mkdir($d,0755,true);if(!copy($src,$dst))throw new RuntimeException('Falha ao restaurar '.$dst);};
foreach(array_reverse($m['files']??[]) as $e){$rel=$e['path'];$dst=$root.'/'.$rel;if(!empty($e['existed'])){$src=rtrim($backup,'/').'/files/'.$rel;if(is_file($src))$copy($src,$dst);}elseif(is_file($dst))@unlink($dst);}
echo "[OK] Arquivos restaurados a partir de {$backup}.\n";
echo "As migrations são aditivas e não são revertidas automaticamente para evitar perda de dados. O código anterior ignora as estruturas extras.\n";
