<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
$dirs=glob($root.'/storage/update-backups/rc1-go-*',GLOB_ONLYDIR)?:[];
rsort($dirs,SORT_STRING);$latest=$dirs[0]??null;
if(!$latest){fwrite(STDERR,"Nenhum backup RC1 encontrado.\n");exit(1);}
$base=$latest.'/files';
if(!is_dir($base)){fwrite(STDERR,"Backup de arquivos inválido: {$latest}\n");exit(1);}
// Remove primeiro apenas o bloco de cron gerenciado pelo RC1, preservando todos os demais.
if(is_file($root.'/tools/install-rc1-crons.php')){
    $o=[];$c=0;@exec(escapeshellarg(PHP_BINARY).' '.escapeshellarg($root.'/tools/install-rc1-crons.php').' --remove --apply 2>&1',$o,$c);
    echo implode("\n",$o)."\n";
    if($c!==0)echo "[AVISO] Não foi possível remover automaticamente o bloco de cron RC1.\n";
}
$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($base,FilesystemIterator::SKIP_DOTS));
$count=0;foreach($it as $f){if(!$f->isFile())continue;$rel=substr($f->getPathname(),strlen($base)+1);$to=$root.'/'.$rel;if(!is_dir(dirname($to)))mkdir(dirname($to),0750,true);if(!copy($f->getPathname(),$to)){fwrite(STDERR,"Falha restaurando {$rel}\n");exit(1);}$count++;}
// Remove arquivos novos do RC1 que não existiam antes, exceto a migration 043 (mantida por compatibilidade).
foreach(['app/Core/CronLock.php','tests/rc1_regression_static.php','tools/install-rc1-crons.php','tools/rc1-repair-jobs.php','tools/rc1-acceptance.php','tools/rc1-go-live.php','tools/rc1-verify-backup.php'] as $rel){if(!is_file($base.'/'.$rel)&&is_file($root.'/'.$rel))@unlink($root.'/'.$rel);}
echo "[OK] {$count} arquivo(s) anteriores restaurados de {$latest}.\n";
echo "A migration 043 é compatível e não é removida automaticamente para evitar perda de diagnóstico/estado.\n";
echo "O rollback também tentou remover o bloco APPLANNER_RC1 do crontab, preservando os demais.\n";
