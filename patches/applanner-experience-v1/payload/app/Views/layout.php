<?php
use App\Core\{Auth,CSRF,Authorization,SubscriptionAccess,Database,I18n};
use App\Services\{ModuleService,LegalDocumentService,ReferralAttributionService,ArenaTenantService,AutoTenantService};
$app=require __DIR__.'/../../config/app.php';
$user=Auth::user();ReferralAttributionService::attributeCurrentUser($user);$path=parse_url($_SERVER['REQUEST_URI']??'/',PHP_URL_PATH)?:'/';
$isPublic=!$user||isset($publicLayout);
$restricted=$user&&!empty($user['tenant_id'])&&(SubscriptionAccess::current()['restricted']??false);
$isPlatform=$user&&empty($user['tenant_id']);
$masterViewModules=$isPlatform&&isset($modules)?$modules:null;$modules=[];$tenantCategory='';$tenantIdentity=[];if($user&&!$isPlatform){try{$modules=ModuleService::enabledForTenant((int)$user['tenant_id']);$q=Database::connection()->prepare('SELECT category,name,logo_path,primary_color,menu_color,menu_text_color,background_color,text_color,font_family,font_size FROM tenants WHERE id=:id');$q->execute(['id'=>(int)$user['tenant_id']]);$tenantIdentity=$q->fetch()?:[];$tenantCategory=(string)($tenantIdentity['category']??'');}catch(Throwable){$modules=[];$tenantCategory='';$tenantIdentity=[];}}
$normalizedTenantCategory=mb_strtolower(trim($tenantCategory));
$isSportsTenant=!empty($modules['sports_courts']);
$isAutoTenant=!$isSportsTenant&&AutoTenantService::isAutoCategory($normalizedTenantCategory);
$isBarberTenant=!$isSportsTenant&&!$isAutoTenant&&in_array($normalizedTenantCategory,['barbearia','barber','barbershop'],true);
$unreadNotifications=0;if($user&&($isPlatform||Authorization::allows('notifications.view'))){try{$nq=Database::connection()->prepare('SELECT COUNT(*) FROM user_notifications WHERE user_id=:u AND read_at IS NULL');$nq->execute(['u'=>(int)$user['id']]);$unreadNotifications=(int)$nq->fetchColumn();}catch(Throwable){$unreadNotifications=0;}}
$headerEyebrow=$restricted?'Acesso para regularização':($isPlatform?'Administração':($isSportsTenant?'Gestão da Arena':($isAutoTenant?'Gestão Automotiva':($isBarberTenant?'Gestão da Barbearia':((($user['role']??'')==='professional')?'Área do profissional':'Operação')))));
$brandSubtitle=$isPlatform?'Administração da plataforma':($isSportsTenant?'ApPlanner Arena':($isAutoTenant?'ApPlanner Auto':($isBarberTenant?'ApPlanner Barber':((($user['role']??'')==='professional')?'Portal profissional':'Gestão inteligente'))));
$pendingLegal=[];if($user&&!$isPlatform&&!isset($publicLayout)){try{$pendingLegal=LegalDocumentService::pendingForUser((int)$user['id']);}catch(Throwable){$pendingLegal=[];}}

if($isPlatform){
    $nav=[];
    if(($user['role']??'')==='master'){
        $nav=[['Painel','/master'],['Clientes da plataforma','/master/tenants'],['Planos','/master/plans'],['Catálogo de módulos','/master/modulos'],['Financeiro da plataforma','/master/financeiro'],['Suporte','/master/support'],['E-mail marketing','/master/email-marketing'],['Blog','/master/blog'],['Configurações de conversão','/master/conversion-settings'],['Saúde do sistema','/master/system-health'],['Central de erros','/master/errors'],['Backups','/master/backups']];
    }elseif(($user['role']??'')==='commercial'){
        $nav=[['Painel comercial','/comercial'],['Oportunidades','/comercial/oportunidades'],['Planos disponíveis','/planos']];if(Auth::commercialSupportEnabled())$nav[]=['Chamados designados','/support'];
    }else{
        if(Authorization::allows('master.support.manage'))$nav[]=['Suporte','/master/support'];
        if(Authorization::allows('master.login_audit.view'))$nav[]=['Auditoria de login','/master/login-audit'];
    }
}elseif($restricted){
    $nav=[['Minha assinatura','/billing'],['Módulos adicionais','/billing/modulos'],['Suporte','/support'],['Segurança','/security']];
}elseif(($user['role']??'')==='professional'&&!$isSportsTenant&&!$isAutoTenant){
    $nav=[['Início','/dashboard'],['Minha agenda','/appointments'],['Minha disponibilidade','/professional/availability']];
    if(Authorization::allows('agenda.blocks.manage'))$nav[]=['Folgas e bloqueios','/schedule/blocks'];
    if(!empty($modules['products'])&&Authorization::allows('sales.view'))$nav[]=['PDV / Minhas vendas','/sales'];
    if($isBarberTenant&&Authorization::allows('barber.commands.view'))$nav[]=['Minhas comandas','/barber/commands'];
    if($isBarberTenant&&Authorization::allows('barber.queue.view'))$nav[]=['Fila / Encaixes','/barber/queue'];
    if($isBarberTenant&&Authorization::allows('barber.goals.view'))$nav[]=['Minhas metas','/barber/goals'];
    if(!empty($modules['finance'])&&Authorization::allows('commissions.view'))$nav[]=['Minhas comissões','/commissions'];
    if(!empty($modules['waitlist'])&&Authorization::allows('waitlist.view'))$nav[]=['Lista de espera','/waitlist'];
    if(!empty($modules['medical_records'])&&Authorization::allows('medical_records.view'))$nav[]=['Prontuários','/clinical'];
    if(Authorization::allows('professional.performance'))$nav[]=['Meu desempenho','/professional/performance'];
    if(Authorization::allows('notifications.view'))$nav[]=['Notificações','/notifications'];
    $nav[]=['Suporte','/support'];$nav[]=['Segurança','/security'];
}elseif($isAutoTenant){
    $nav=array_values(array_filter([
        Authorization::allows('auto.dashboard.view')?['Dashboard Auto','/auto']:null,
        Authorization::allows('auto.jobs.view')?['Ordens / Serviços','/auto/jobs']:null,
        Authorization::allows('auto.jobs.manage')?['Novo atendimento','/auto/bookings/create']:null,
        Authorization::allows('vehicles.view')?['Veículos','/vehicles']:null,
        Authorization::allows('auto.bays.view')?['Boxes / Vagas','/auto/bays']:null,
        Authorization::allows('customers.view')?['Clientes','/customers']:null,
        Authorization::allows('services.view')?['Serviços','/services']:null,
        Authorization::allows('professionals.manage')?['Equipe','/professionals']:null,
        Authorization::allows('auto.commands.view')?['Comandas','/auto/commands']:null,
        (!empty($modules['products'])&&Authorization::allows('products.view'))?['Produtos','/products']:null,
        (!empty($modules['stock'])&&Authorization::allows('products.stock'))?['Estoque','/stock']:null,
        (!empty($modules['packages'])&&Authorization::allows('packages.view'))?['Pacotes / Planos','/packages']:null,
        Authorization::allows('auto.crm.view')?['CRM Automotivo','/auto/crm']:null,
        (!empty($modules['finance'])&&Authorization::allows('finance.view'))?['Financeiro','/finance']:null,
        (!empty($modules['finance'])&&Authorization::allows('commissions.view'))?['Comissões','/commissions']:null,
        Authorization::allows('auto.reports.view')?['Relatórios','/auto/reports']:null,
        Authorization::allows('auto.settings.manage')?['Configurações Auto','/auto/settings']:null,
        (($user['role']??'')==='owner')?['Aparência','/settings/branding']:null,
        ['Suporte','/support'],['Minha assinatura','/billing'],['Módulos adicionais','/billing/modulos'],['Segurança','/security']
    ]));
}elseif($isSportsTenant){
    $nav=array_values(array_filter([
        ['Dashboard','/sports'],
        Authorization::allows('sports.agenda.view')?['Agenda','/sports/agenda']:null,
        Authorization::allows('sports.view')?['Quadras/Espaços','/sports/courts']:null,
        Authorization::allows('sports.view')?['Reservas','/sports/reservations']:null,
        Authorization::allows('sports.games.manage')?['Rachas','/sports/games']:null,
        Authorization::allows('sports.memberships.manage')?['Mensalistas','/sports/memberships']:null,
        Authorization::allows('sports.waitlist.manage')?['Lista de Espera','/sports/waitlist']:null,
        (!empty($modules['sports_academy'])&&Authorization::allows('sports.academy.manage'))?['Aulas/Escolinha','/sports/classes']:null,
        (!empty($modules['sports_tournaments'])&&Authorization::allows('sports.tournaments.manage'))?['Torneios','/sports/tournaments']:null,
        Authorization::allows('customers.view')?['Clientes/Jogadores','/customers']:null,
        Authorization::allows('sports.commands.manage')?['Comandas','/sports/commands']:null,
        (!empty($modules['products'])&&Authorization::allows('products.view'))?['Produtos','/products']:null,
        (!empty($modules['stock'])&&Authorization::allows('products.stock'))?['Estoque','/stock']:null,
        (!empty($modules['finance'])&&Authorization::allows('finance.view'))?['Financeiro','/finance']:null,
        Authorization::allows('sports.reports.view')?['Relatórios','/sports/reports']:null,
        (!empty($modules['banking_integrations'])&&Authorization::allows('banking.view'))?['Bancos e Pagamentos','/settings/banking']:null,
        Authorization::allows('sports.manage')?['Configurações da Arena','/sports/arena-settings']:null,
        (($user['role']??'')==='owner')?['Aparência','/settings/branding']:null,
        ['Suporte','/support'],['Minha assinatura','/billing'],['Módulos adicionais','/billing/modulos'],['Segurança','/security']
    ]));
}else{
    $nav=array_values(array_filter([
        ['Visão geral','/dashboard'],$isSportsTenant?null:['Agenda','/appointments'],
        ($isBarberTenant&&Authorization::allows('barber.queue.view'))?['Fila / Encaixes','/barber/queue']:null,
        ($isBarberTenant&&Authorization::allows('barber.commands.view'))?['Comandas','/barber/commands']:null,
        (!$isSportsTenant&&Authorization::allows('agenda.blocks.manage'))?['Folgas e bloqueios','/schedule/blocks']:null,
        (!$isSportsTenant&&Authorization::allows('agenda.settings.manage'))?['Regras da agenda','/schedule/settings']:null,
        ['Clientes','/customers'],$isSportsTenant?null:['Profissionais','/professionals'],$isSportsTenant?null:['Serviços','/services'],
        ($isBarberTenant&&Authorization::allows('barber.goals.view'))?['Metas da equipe','/barber/goals']:null,
        (in_array($tenantCategory,['lava_jato','lava-jato','lava jato','detailing','automotivo','automotive'],true)&&Authorization::allows('vehicles.view'))?['Veículos','/vehicles']:null,
        (!empty($modules['products'])&&Authorization::allows('products.view'))?['Produtos','/products']:null,
        (!empty($modules['products'])&&Authorization::allows('sales.view'))?['PDV / Vendas','/sales']:null,
        (!empty($modules['stock'])&&Authorization::allows('products.stock'))?['Estoque','/stock']:null,
        (!empty($modules['finance'])&&Authorization::allows('commissions.view'))?['Comissões','/commissions']:null,
        (!empty($modules['packages'])&&Authorization::allows('packages.view'))?['Pacotes','/packages']:null,
        (!empty($modules['loyalty'])&&Authorization::allows('loyalty.view'))?['Fidelidade','/loyalty']:null,
        (!empty($modules['waitlist'])&&Authorization::allows('waitlist.view'))?['Lista de espera','/waitlist']:null,
        (!empty($modules['sports_courts'])&&Authorization::allows('sports.view'))?['Quadras e Esportes','/sports']:null,
        (!empty($modules['finance'])&&Authorization::allows('finance.view'))?['Financeiro','/finance']:null,
        Authorization::allows('units.view')?['Unidades','/units']:null,
        (!empty($modules['behavior'])&&Authorization::allows('dashboard.view'))?['Inteligência','/intelligence']:null,
        Authorization::allows('dashboard.view')?['Conversas WhatsApp','/whatsapp']:null,
        (!empty($modules['medical_records'])&&Authorization::allows('medical_records.view'))?['Prontuários','/clinical']:null,
        (!empty($modules['custom_domain'])&&Authorization::allows('domains.manage'))?['Domínio próprio','/domains']:null,
        Authorization::allows('reports.view')?['Relatórios','/reports']:null,
        Authorization::allows('notifications.view')?['Notificações','/notifications']:null,
        (($user['role']??'')==='owner')?['Aparência','/settings/branding']:null,
        ['Suporte','/support'],['Minha assinatura','/billing'],['Módulos adicionais','/billing/modulos'],['Segurança','/security']
    ]));
}
$nav=isset($nav)?array_map(static fn(array $item):array=>[I18n::label((string)$item[0]),$item[1]],$nav):[];
$activeHref='';
if(isset($nav)){
    foreach($nav as $item){if($path===$item[1]){$activeHref=$item[1];break;}}
    if($activeHref==='')foreach($nav as $item){$href=$item[1];if(str_starts_with($path,rtrim($href,'/').'/')&&strlen($href)>strlen($activeHref))$activeHref=$href;}
}
$active=fn(string $href):bool=>$href===$activeHref;
$sidebarScrollKey='applanner-sidebar-v2-'.(int)($user['id']??0);
?>
<!doctype html><html lang="pt-BR" data-theme="auto"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="csrf-token" content="<?=htmlspecialchars(CSRF::token(),ENT_QUOTES,'UTF-8')?>"><meta name="theme-color" content="#29223d"><script>(function(){try{var t=localStorage.getItem('agenda-theme');if(['auto','light','dark'].includes(t))document.documentElement.dataset.theme=t}catch(e){}})();</script><link rel="icon" type="image/png" href="/public/assets/brand/applanner-symbol.png"><title><?=htmlspecialchars(($title??'Sistema').' • '.($app['name']??'ApPlanner'),ENT_QUOTES,'UTF-8')?></title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet"><link href="/public/assets/css/app.css" rel="stylesheet"><link href="/public/assets/css/brand-blog.css" rel="stylesheet"><link href="/public/assets/css/v43-responsive-fix.css" rel="stylesheet"><link href="/public/assets/css/commercial-team.css" rel="stylesheet"><link href="/public/assets/css/public-booking-v2.css" rel="stylesheet"><link href="/public/assets/css/theme-device.css?v=20260808" rel="stylesheet"><link href="/public/assets/css/theme-customer.css?v=20260808" rel="stylesheet"><link href="/public/assets/css/public-directory.css?v=20260808" rel="stylesheet"><link href="/public/assets/css/operations-center.css?v=20260813" rel="stylesheet"><link href="/public/assets/css/company-customer-experience.css?v=20260813" rel="stylesheet"><link href="/public/assets/css/index-conversion.css?v=20260818-showcase" rel="stylesheet"><link href="/public/assets/css/sports-module.css?v=20260818-arena-v1" rel="stylesheet"></head>
<body class="<?=$isPublic?'public-shell':'app-shell'?> <?=!$isPlatform&&!empty($tenantIdentity['logo_path'])?'has-tenant-logo':''?>"<?php if(!$isPlatform&&$tenantIdentity):?> style="--primary:<?=htmlspecialchars($tenantIdentity['primary_color']??'#3157d5',ENT_QUOTES,'UTF-8')?>;--sidebar:<?=htmlspecialchars($tenantIdentity['menu_color']??'#17213b',ENT_QUOTES,'UTF-8')?>;--sidebar-text:<?=htmlspecialchars($tenantIdentity['menu_text_color']??'#dce3f7',ENT_QUOTES,'UTF-8')?>;--page:<?=htmlspecialchars($tenantIdentity['background_color']??'#f4f6fb',ENT_QUOTES,'UTF-8')?>;--text:<?=htmlspecialchars($tenantIdentity['text_color']??'#17213b',ENT_QUOTES,'UTF-8')?>;--tenant-font:'<?=htmlspecialchars($tenantIdentity['font_family']??'Inter',ENT_QUOTES,'UTF-8')?>';--tenant-font-size:<?=(int)($tenantIdentity['font_size']??15)?>px;--tenant-logo:url('<?=htmlspecialchars($tenantIdentity['logo_path']??'',ENT_QUOTES,'UTF-8')?>')"<?php endif;?>>
<?php if($user&&!isset($publicLayout)):?>
<aside class="app-sidebar" id="appSidebar" aria-label="Navegação principal"><a class="brand" href="<?=$isPlatform?'/master':($isSportsTenant?'/sports':'/dashboard')?>"><span class="brand-mark">A</span><span class="brand-copy"><strong><?=htmlspecialchars($app['name']??'Agenda',ENT_QUOTES,'UTF-8')?></strong><small><?=htmlspecialchars($brandSubtitle,ENT_QUOTES,'UTF-8')?></small></span></a><button class="sidebar-collapse-button" type="button" data-sidebar-collapse aria-label="Recolher menu" title="Recolher menu"><span>⇤</span><b>Recolher menu</b></button><div class="sidebar-label">Navegação</div><nav class="sidebar-nav" id="sidebarNav" data-scroll-key="<?=htmlspecialchars($sidebarScrollKey,ENT_QUOTES,'UTF-8')?>"><?php foreach($nav as [$label,$href]):?><a href="<?=$href?>" class="<?=$active($href)?'active':''?>" <?=$active($href)?'aria-current="page"':''?>><span class="nav-dot"></span><span><?=$label?></span></a><?php endforeach;?></nav><div class="sidebar-footer"><div class="user-avatar"><?=htmlspecialchars(mb_strtoupper(mb_substr($user['name'],0,1)),ENT_QUOTES,'UTF-8')?></div><div class="user-copy"><strong><?=htmlspecialchars($user['name'],ENT_QUOTES,'UTF-8')?></strong><small><?=htmlspecialchars($user['email'],ENT_QUOTES,'UTF-8')?></small></div><form method="post" action="/logout"><?=CSRF::field()?><button class="icon-button" aria-label="Sair" title="Sair">↗</button></form></div></aside>
<script>(function(){var n=document.getElementById('sidebarNav');if(!n)return;var k=n.dataset.scrollKey;var saved=null;try{saved=sessionStorage.getItem(k)}catch(e){}if(saved!==null&&isFinite(Number(saved)))n.scrollTop=Number(saved);else{var current=n.querySelector('[aria-current="page"]');if(current)current.scrollIntoView({block:'nearest',inline:'nearest'});}var save=function(){try{sessionStorage.setItem(k,String(n.scrollTop))}catch(e){}};n.addEventListener('scroll',save,{passive:true});n.addEventListener('click',function(e){if(e.target.closest('a'))save()});window.addEventListener('pagehide',save);})();</script>
<div class="app-backdrop" data-sidebar-close></div><div class="app-frame"><header class="app-header"><button class="icon-button mobile-menu" data-sidebar-toggle aria-label="Abrir menu">☰</button><div><div class="eyebrow"><?=htmlspecialchars($headerEyebrow,ENT_QUOTES,'UTF-8')?></div><div class="header-title"><?=htmlspecialchars($title??'Visão geral',ENT_QUOTES,'UTF-8')?></div></div><div class="header-actions"><?php if($isPlatform||Authorization::allows('notifications.view')):?><a class="icon-button position-relative text-decoration-none" href="/notifications" aria-label="Notificações" title="Notificações">🔔<?php if($unreadNotifications>0):?><span class="position-absolute top-0 start-100 translate-middle badge rounded-pill text-bg-danger"><?=$unreadNotifications>99?'99+':$unreadNotifications?></span><?php endif;?></a><?php endif;?><button class="icon-button" data-theme-toggle aria-label="Alternar tema" title="Tema">◐</button><?php if(!$restricted&&!$isPlatform&&($user['role']??'')!=='professional'):?><button class="search-trigger" data-command-open aria-label="Abrir busca"><span>⌕</span><span class="d-none d-sm-inline">Buscar</span><kbd class="d-none d-lg-inline">Ctrl K</kbd></button><a class="btn btn-primary global-new" href="<?=$isSportsTenant?'/sports/reservations':($isAutoTenant?'/auto/bookings/create':'/appointments/create')?>"><?=$isSportsTenant?'+ Nova reserva':($isAutoTenant?'+ Atendimento':'+ Novo')?></a><?php endif;?></div></header><main class="app-content" id="main-content">
<?php if(Auth::isSupportImpersonating()):$sm=Auth::supportMeta();?><div class="alert alert-danger d-flex flex-wrap align-items-center justify-content-between gap-2"><div><strong>MODO SUPORTE ATIVO.</strong> Você está acessando a conta do cliente pelo chamado #<?=htmlspecialchars((string)($sm['ticket_id']??''),ENT_QUOTES,'UTF-8')?>. Todas as ações devem ser estritamente necessárias ao suporte.</div><form method="post" action="/support/end-access"><?=CSRF::field()?><button class="btn btn-danger btn-sm">Encerrar acesso</button></form></div><?php endif;?>
<?php if($pendingLegal):?><div class="alert alert-warning d-flex flex-wrap justify-content-between align-items-center gap-2"><div><strong>Documentos atualizados.</strong> Há uma nova versão dos Termos de Uso ou da Política de Privacidade aguardando seu aceite.</div><a class="btn btn-sm btn-warning" href="/aceite-legal">Ler e aceitar</a></div><?php endif;?><?php if($restricted):?><div class="billing-mode-banner" role="status"><strong>Conta em modo de cobrança.</strong><span>Seus dados permanecem preservados. Regularize o pagamento para liberar os módulos.</span></div><?php endif;?><?php if($isPlatform&&$masterViewModules!==null)$modules=$masterViewModules;require $viewFile;?></main></div>
<?php if(!$restricted&&!$isPlatform):?><nav class="mobile-bottom-nav" aria-label="Atalhos"><a href="<?=$isSportsTenant?'/sports':($isAutoTenant?'/auto':'/dashboard')?>">Início</a><a href="<?=$isSportsTenant?'/sports/reservations':($isAutoTenant?'/auto/jobs':'/appointments')?>"><?=$isSportsTenant?'Reservas':($isAutoTenant?'Ordens':'Agenda')?></a><?php if(($user['role']??'')!=='professional'):?><a class="new" href="<?=$isSportsTenant?'/sports/reservations':($isAutoTenant?'/auto/bookings/create':'/appointments/create')?>">+</a><a href="/customers">Clientes</a><?php elseif(!empty($modules['products'])):?><a class="new" href="/sales">$</a><a href="/professional/availability">Horários</a><?php endif;?><button data-sidebar-toggle>Menu</button></nav><?php endif;?>
<?php else:?><?php $publicHasPlans=!isset($plans)||!is_array($plans)||count($plans)>0;?><header class="public-header"><a class="public-brand-logo-link" href="/" aria-label="ApPlanner"><img src="/public/assets/brand/applanner-logo.png" alt="ApPlanner"></a><nav class="public-nav" aria-label="Navegação do site"><a href="/estabelecimentos">Perto de você</a><a href="/#funcionalidades">Funcionalidades</a><?php if($publicHasPlans):?><a href="/planos">Planos</a><?php endif;?><a href="/blog">Blog</a><a href="/login">Entrar</a><a class="btn btn-primary" href="<?=$publicHasPlans?'/cadastro':'/interesse-comercial'?>"><?=$publicHasPlans?'Teste grátis':'Falar com comercial'?></a><button class="icon-button" data-theme-toggle aria-label="Alternar tema">◐</button></nav></header><main class="public-content"><?php require $viewFile;?></main><?php endif;?>
<div class="command-dialog" data-command-dialog hidden><div class="command-panel" role="dialog" aria-modal="true" aria-label="Busca rápida"><div class="command-input"><span>⌕</span><input data-command-input placeholder="<?=$isSportsTenant?'Buscar clientes e reservas':($isAutoTenant?'Buscar veículos e ordens':'Buscar clientes e agenda')?>" aria-label="Buscar"><button data-command-close aria-label="Fechar">Esc</button></div><div class="command-results"><a href="/customers">Clientes</a><?php if($isSportsTenant):?><a href="/sports/reservations">Reservas de quadras</a><a href="/sports/courts">Quadras e horários</a><?php elseif($isAutoTenant):?><a href="/auto/jobs">Ordens automotivas</a><a href="/vehicles">Veículos</a><a href="/auto/commands">Comandas</a><?php elseif($isBarberTenant):?><a href="/appointments">Agenda</a><a href="/barber/commands">Comandas</a><a href="/barber/queue">Fila / Encaixes</a><?php else:?><a href="/appointments">Agenda</a><a href="/services">Serviços</a><?php endif;?></div></div></div><div class="toast-region" aria-live="polite" aria-atomic="true"></div><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script><script src="/public/assets/js/app.js?v=20260808-theme-auto"></script><script src="/public/assets/js/sidebar-collapse.js?v=20260813"></script></body></html>
