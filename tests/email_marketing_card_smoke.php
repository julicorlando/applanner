<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);require $root.'/app/Core/bootstrap.php';
$checks=[];$ok=function(string $n,bool $v,string $d='')use(&$checks){$checks[]=[$n,$v];echo ($v?'[OK] ':'[FALHA] ').$n.($d!==''?' — '.$d:'').PHP_EOL;};
$ok('Migration 045',is_file($root.'/database/migrations/045_email_marketing_card.sql'));
$ok('Serviço de upload',is_file($root.'/app/Services/EmailMarketingCardService.php'));
$ok('Template HTML',is_file($root.'/app/Services/EmailMarketingTemplateService.php'));
$ok('SMTP sendHtml',method_exists(\App\Services\SmtpProvider::class,'sendHtml'));
$c=(string)@file_get_contents($root.'/app/Controllers/LeadMarketingController.php');$v=(string)@file_get_contents($root.'/app/Views/master/lead-marketing.php');$w=(string)@file_get_contents($root.'/cron/worker.php');
$ok('Controller aceita card',str_contains($c,'card_image')&&str_contains($c,'image_alt')&&str_contains($c,'card_link_url'));
$ok('Form multipart',str_contains($v,'enctype="multipart/form-data"'));
$ok('Pré-visualização',str_contains($v,'marketingCardPreview'));
$ok('Worker envia HTML',str_contains($w,'EmailMarketingTemplateService')&&str_contains($w,'sendHtml'));
$t=(new \App\Services\EmailMarketingTemplateService())->build(['message'=>"Olá João,\nConheça o ApPlanner.",'referral_url'=>'https://applanner.com.br/indicacao/1234567890abcdef?c=1&l=1','unsubscribe_url'=>'https://applanner.com.br/email/descadastrar/'.str_repeat('a',64),'referrer_name'=>'Equipe ApPlanner','image_url'=>'https://applanner.com.br/public/uploads/email-marketing/2026/08/card.jpg','image_alt'=>'Card ApPlanner']);
$ok('HTML contém card',str_contains($t['html'],'<img')&&str_contains($t['html'],'card.jpg'));
$ok('Fallback texto',str_contains($t['text'],'Card da campanha:')&&str_contains($t['text'],'Não deseja mais receber novidades?'));
$bad=array_filter($checks,fn($x)=>!$x[1]);if($bad){fwrite(STDERR,"email marketing card smoke: FALHOU\n");exit(1);}echo "email marketing card smoke: OK (".count($checks)." verificações)\n";
