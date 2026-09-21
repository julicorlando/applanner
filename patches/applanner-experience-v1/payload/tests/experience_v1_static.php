<?php
declare(strict_types=1);if(PHP_SAPI!=='cli'){exit(1);}$root=dirname(__DIR__);$checks=[];$ok=true;
function check(bool $condition,string $label):void{global $checks,$ok;$checks[]=[$condition,$label];if(!$condition)$ok=false;}
check(is_file($root.'/app/Core/I18n.php'),'núcleo i18n');foreach(['pt_BR','pt_PT','en','es'] as $locale)check(is_file($root.'/app/Lang/'.$locale.'.php'),'idioma '.$locale);
$index=(string)file_get_contents($root.'/index.php');check(str_contains($index,"/master/conversion-settings"),'rota aquisição');
$migration=(string)file_get_contents($root.'/database/migrations/044_applanner_experience_i18n_growth.sql');check(str_contains($migration,'cron_heartbeats'),'schema heartbeat');check(str_contains($migration,'public_headline'),'schema personalização');
$cron=(string)file_get_contents($root.'/tools/applanner-cron-health.php');foreach(['worker','appointment_reminders','arena','barber','auto','backup'] as $key)check(str_contains($cron,"'{$key}'"),'cron '.$key);
$landing=(string)file_get_contents($root.'/app/Views/commercial/landing.php');check(str_contains($landing,'data-meta-pixel-id'),'pixel com consentimento');check(str_contains($landing,"I18n::t('landing.title')"),'landing traduzível');
foreach($checks as [$pass,$label])echo ($pass?'[OK] ':'[FALHA] ').$label."\n";exit($ok?0:1);
