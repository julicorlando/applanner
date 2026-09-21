<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);$payload=$root.'/patches/applanner-email-marketing-card-v1/payload';require $root.'/app/Core/bootstrap.php';
use App\Core\Database;
function fail(string $m):never{fwrite(STDERR,"[ERRO] {$m}\n");exit(1);}
function copyTree(string $src,string $dst):void{$it=new RecursiveIteratorIterator(new RecursiveDirectoryIterator($src,FilesystemIterator::SKIP_DOTS),RecursiveIteratorIterator::SELF_FIRST);foreach($it as $f){$rel=substr($f->getPathname(),strlen($src)+1);$to=$dst.'/'.$rel;if($f->isDir()){if(!is_dir($to))@mkdir($to,0755,true);continue;}if(!is_dir(dirname($to)))@mkdir(dirname($to),0755,true);if(!copy($f->getPathname(),$to))fail('Falha copiando '.$rel);}}
if(!is_dir($payload))fail('Payload não encontrado. Extraia o ZIP em public_html.');
echo "APPLANNER — EMAIL MARKETING CARD V1\n===================================\n";
foreach(['app/Controllers/LeadMarketingController.php','app/Services/SmtpProvider.php','app/Views/master/lead-marketing.php','cron/worker.php'] as $rel)if(!is_file($root.'/'.$rel))fail('Arquivo base ausente: '.$rel);
$backup=$root.'/storage/update-backups/email-marketing-card-'.date('Ymd-His');
foreach(['app/Controllers/LeadMarketingController.php','app/Services/SmtpProvider.php','app/Views/master/lead-marketing.php','cron/worker.php'] as $rel){$to=$backup.'/'.$rel;@mkdir(dirname($to),0750,true);if(!copy($root.'/'.$rel,$to))fail('Backup falhou: '.$rel);}
echo "[OK] Backup de código: {$backup}\n";
copyTree($payload,$root);echo "[OK] Arquivos copiados.\n";
$pdo=Database::connection();try{\App\Core\Migrator::run($pdo,$root.'/database/migrations');}catch(Throwable $e){fail('Migration falhou: '.$e->getMessage());}
echo "[OK] Migration 045 aplicada.\n";
$cols=$pdo->query("SHOW COLUMNS FROM marketing_campaigns")->fetchAll(PDO::FETCH_COLUMN);foreach(['image_path','image_url','image_alt','card_link_url'] as $c)if(!in_array($c,$cols,true))fail('Coluna não criada: '.$c);
$upload=$root.'/public/uploads/email-marketing';if(!is_dir($upload)&&!mkdir($upload,0755,true)&&!is_dir($upload))fail('Pasta de upload não criada.');
@file_put_contents($upload.'/.htaccess',"Options -Indexes\n<FilesMatch \"\\.(php|phtml|phar|cgi|pl|py|sh)$\">\nRequire all denied\n</FilesMatch>\n",LOCK_EX);
echo "[OK] Pasta de cards protegida.\n";
echo "Instalação concluída. Execute: php tests/email_marketing_card_smoke.php\n";
