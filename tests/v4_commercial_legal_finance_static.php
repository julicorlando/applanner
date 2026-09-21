<?php
declare(strict_types=1);
$root=dirname(__DIR__);
$files=[
 'routes'=>file_get_contents($root.'/index.php'),
 'migration'=>file_get_contents($root.'/database/migrations/016_v4_commercial_legal_modules_finance.sql'),
 'legal'=>file_get_contents($root.'/app/Services/LegalDocumentService.php'),
 'legalController'=>file_get_contents($root.'/app/Controllers/LegalController.php'),
 'moduleController'=>file_get_contents($root.'/app/Controllers/ModuleController.php'),
 'metrics'=>file_get_contents($root.'/app/Services/PlatformMetricsService.php'),
 'finance'=>file_get_contents($root.'/app/Controllers/PlatformFinanceController.php'),
 'mp'=>file_get_contents($root.'/app/Controllers/MercadoPagoController.php'),
 'webhook'=>file_get_contents($root.'/app/Controllers/WebhookController.php'),
 'planView'=>file_get_contents($root.'/app/Views/master/plan-form.php'),
 'masterView'=>file_get_contents($root.'/app/Views/master/index.php'),
 'landing'=>file_get_contents($root.'/app/Views/commercial/landing.php'),
];
$checks=[
 'LEGAL-DOCS'=>str_contains($files['migration'],'CREATE TABLE IF NOT EXISTS legal_documents')&&str_contains($files['migration'],'CREATE TABLE IF NOT EXISTS legal_acceptances')&&str_contains($files['routes'],"'/termos'")&&str_contains($files['routes'],"'/privacidade'")&&str_contains($files['legal'],'TERMOS DE USO')&&str_contains($files['legal'],'POLÍTICA DE PRIVACIDADE'),
 'LEGAL-ACCEPTANCE-GATE'=>str_contains($files['routes'],'pendingForUser')&&str_contains($files['legalController'],'legal_acceptances'),
 'LEGAL-AUDIT'=>str_contains($files['legalController'],'accepted_at')&&str_contains(file_get_contents($root.'/app/Views/master/legal-documents.php'),'Últimos aceites registrados'),
 'PLAN-MODULES'=>str_contains($files['planView'],'modules[]')&&str_contains($files['planView'],'Módulos incluídos no plano')&&str_contains($files['planView'],'Gerenciar catálogo'),
 'MODULE-CATALOG'=>str_contains($files['migration'],'addon_monthly_price')&&str_contains($files['migration'],'addon_sellable')&&str_contains($files['routes'],"'/master/modulos'")&&str_contains($files['routes'],"'/billing/modulos'"),
 'MODULE-REQUEST'=>str_contains($files['migration'],'CREATE TABLE IF NOT EXISTS module_requests')&&str_contains($files['moduleController'],'quoted_monthly_price')&&str_contains($files['moduleController'],'createSubscription'),
 'MODULE-CANCEL-FALLBACK'=>str_contains($files['moduleController'],'DELETE FROM tenant_modules WHERE tenant_id=:t AND module_id=:m'),
 'MASTER-FINANCE'=>str_contains($files['migration'],'CREATE TABLE IF NOT EXISTS platform_financial_transactions')&&str_contains($files['routes'],"'/master/financeiro'")&&str_contains($files['finance'],'PlatformMetricsService'),
 'MASTER-METRICS'=>str_contains($files['metrics'],"'mrr'")&&str_contains($files['metrics'],"'arr'")&&str_contains($files['metrics'],"'forecast_30d'")&&str_contains($files['masterView'],'Previsão em 30 dias'),
 'MP-MULTI-ENV'=>str_contains($files['migration'],'uq_gateway_provider_environment')&&str_contains($files['mp'],"['sandbox','production']")&&str_contains($files['mp'],'mercadopago.sandbox_validated_at'),
 'MP-ADDON-WEBHOOK'=>str_contains($files['webhook'],"module_addon")&&str_contains($files['webhook'],'tenant_module_addons'),
 'LANDING-V4'=>str_contains($files['landing'],'Organize a operação')&&str_contains($files['landing'],'Inteligência de retorno')&&str_contains($files['landing'],'segurança'),
 'PORTUGUESE-PLANS'=>str_contains($files['migration'],"name='Inicial'")&&str_contains($files['migration'],"name='Empresarial'")&&str_contains($files['migration'],"name='Saúde'"),
];
$failed=[];foreach($checks as $id=>$ok){echo $id.' '.($ok?'PASS':'FAIL').PHP_EOL;if(!$ok)$failed[]=$id;}if($failed){fwrite(STDERR,'Falhas: '.implode(', ',$failed).PHP_EOL);exit(1);}exit(0);
