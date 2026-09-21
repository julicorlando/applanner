<?php
use App\Core\CSRF;
$tenant=\App\Services\PublicTranslationService::apply($tenant,\App\Core\I18n::locale());
$e=fn($v)=>htmlspecialchars((string)$v,ENT_QUOTES,'UTF-8');
$today=date('Y-m-d');
$logo=$tenant['logo_path']??'';
$allowWaitlist=!empty($arenaSettings['allow_waitlist']);
$offer=$waitlistOffer??null;
$headline=$tenant['public_headline']?:$tenant['name'];$subheadline=$tenant['public_subheadline']?:($tenant['description']??'Escolha sua modalidade, quadra e horário.');$ctaLabel=$tenant['public_cta_label']?:'Confirmar reserva';$accent=$tenant['public_accent_color']?:($tenant['primary_color']??'#3157d5');
?>
<?php if(!empty($tenant['public_announcement'])):?><div class="alert alert-primary text-center"><?=$e($tenant['public_announcement'])?></div><?php endif;?>
<section class="arena-public-hero" data-default-locale="<?=$e($tenant['default_locale']??'pt_BR')?>" style="--primary:<?=$e($accent)?>">
  <div>
    <?php if($logo):?><img class="arena-public-logo" src="<?=$e($logo)?>" alt="<?=$e($tenant['name'])?>"><?php endif;?>
    <span class="sports-kicker">APPLANNER ARENA</span>
    <h1><?=$e($headline)?></h1>
    <p><?=$e($subheadline)?></p>
  </div>
</section>
<?php if(!empty($_GET['waitlist'])):?><div class="alert alert-success">Você entrou na lista de espera. A Arena poderá avisar pelos canais que você autorizou se surgir disponibilidade.</div><?php endif;?>
<?php if($offer):?><div class="alert alert-info"><strong>Sua vaga da lista de espera foi liberada.</strong> Esta oferta fica reservada para você até <?=date('d/m/Y H:i',strtotime($offer['offer_expires_at']))?>. Conclua abaixo.</div><?php endif;?>
<section class="arena-layout" id="reservar" data-sports-booking data-endpoint="/arena/<?=$e($routeSlug)?>/availability" data-waitlist-token="<?=$e($offer['public_token']??'')?>">
  <div class="arena-catalog">
    <h2>Quadras e espaços</h2>
    <div class="sports-grid">
      <?php foreach($courts as $c):?>
      <article class="sports-court-card">
        <?php if($c['photo_path']):?><img src="<?=$e($c['photo_path'])?>" alt="<?=$e($c['name'])?>"><?php else:?><div class="sports-photo-placeholder">🏟️</div><?php endif;?>
        <div class="p-3"><h3><?=$e($c['name'])?></h3><p><?=$e($c['description']??'')?></p><small><?=$e($c['modalities']??'')?><?php if($c['surface']):?> · <?=$e($c['surface'])?><?php endif;?><?php if($c['indoor']):?> · Coberta<?php endif;?><?php if($c['lighting']):?> · Iluminada<?php endif;?></small>
        <?php if(!empty($c['slug'])):?><div class="mt-2"><a class="small" href="/arena/<?=$e($routeSlug)?>/quadra/<?=$e($c['slug'])?>">Link desta quadra</a></div><?php endif;?></div>
      </article>
      <?php endforeach;?>
    </div>
  </div>
  <form class="arena-book-card" method="post" action="/arena/<?=$e($routeSlug)?>/reserve">
    <?=CSRF::field()?>
    <?php if($offer):?><input type="hidden" name="waitlist_token" value="<?=$e($offer['public_token'])?>"><?php endif;?>
    <div class="arena-step"><span>1</span><div><strong>Reserve sua quadra</strong><small>Sem profissional no fluxo de reserva</small></div></div>
    <label class="form-label">Modalidade</label>
    <select class="form-select" name="modality_id" data-sports-modality required><option value="">Escolha</option><?php foreach($modalities as $m):?><option value="<?=(int)$m['id']?>" <?=($offer&&(int)$offer['modality_id']===(int)$m['id'])?'selected':''?>><?=$e($m['name'])?></option><?php endforeach;?></select>
    <label class="form-label mt-3">Quadra/Espaço</label>
    <select class="form-select" name="court_id" data-sports-court required disabled><option value="">Escolha primeiro a modalidade</option><?php foreach($courts as $c):?><option value="<?=(int)$c['id']?>" data-modalities="<?=$e((string)($c['modality_ids']??''))?>" data-court-slug="<?=$e($c['slug']??'')?>" <?=($selectedCourtSlug&&$selectedCourtSlug===($c['slug']??''))?'data-preselect="1"':''?> <?=($offer&&(int)$offer['court_id']===(int)$c['id'])?'data-offer-preselect="1"':''?>><?=$e($c['name'])?></option><?php endforeach;?></select>
    <div class="row g-2 mt-1">
      <div class="col-7"><label class="form-label">Data</label><input class="form-control" type="date" name="date" min="<?=$today?>" value="<?=$e($offer['preferred_date']??$today)?>" data-sports-date required></div>
      <div class="col-5"><label class="form-label">Duração</label><select class="form-select" name="duration_minutes" data-sports-duration><?php foreach([60=>'1 hora',90=>'1h30',120=>'2 horas',180=>'3 horas'] as $d=>$label):?><option value="<?=$d?>" <?=($offer&&(int)$offer['duration_minutes']===$d)?'selected':''?>><?=$label?></option><?php endforeach;?></select></div>
    </div>
    <button class="btn btn-primary w-100 mt-3" type="button" data-sports-search>Ver horários disponíveis</button>
    <div class="sports-slots" data-sports-slots aria-live="polite"><p>Escolha os dados acima para consultar a agenda.</p></div>
    <input type="hidden" name="starts_at" data-sports-start required>
    <div data-sports-customer hidden><hr><div class="arena-step"><span>2</span><div><strong>Seus dados</strong><small>Usados para identificar e confirmar a reserva</small></div></div>
      <input class="form-control mb-2" name="name" placeholder="Nome completo" required value="<?=$e($offer['customer_name']??'')?>">
      <input class="form-control mb-2" name="phone" placeholder="WhatsApp com DDD" required value="<?=$e($offer['customer_phone']??'')?>">
      <input class="form-control mb-2" type="email" name="email" placeholder="E-mail" value="<?=$e($offer['customer_email']??'')?>">
      <textarea class="form-control mb-2" name="notes" placeholder="Observação para a Arena"></textarea>
      <div class="form-check mb-3"><input class="form-check-input" type="checkbox" value="1" name="operational_reminders_consent" id="arena-reminder-consent"><label class="form-check-label small" for="arena-reminder-consent">Aceito receber lembretes operacionais desta reserva por WhatsApp ou e-mail, quando o canal estiver disponível.</label></div>
      <label class="form-label">Forma de pagamento</label>
      <select class="form-select mb-2" name="payment_method">
        <?php if(!empty($settings['require_deposit'])):?><option value="pix">Pix</option><?php if(!empty($cardAvailable)):?><option value="card">Cartão</option><?php endif;?><?php else:?><option value="onsite">Pagamento no local</option><option value="pix">Pix</option><?php if(!empty($cardAvailable)):?><option value="card">Cartão</option><?php endif;?><?php endif;?>
      </select>
      <label class="form-check small"><input class="form-check-input" type="checkbox" name="terms" required> Li e aceito as condições da reserva<?php if($settings['booking_terms']):?>: <?=$e($settings['booking_terms'])?><?php endif;?></label>
      <button class="btn btn-primary w-100 mt-3"><?=$e($ctaLabel)?></button>
    </div>
  </form>
</section>
<?php if($allowWaitlist):?>
<section class="card border-0 shadow-sm mt-4" id="lista-espera"><div class="card-body"><div class="section-heading"><div><span class="sports-kicker">LISTA DE ESPERA</span><h2>O horário que você quer está ocupado?</h2><p class="text-secondary mb-0">Cadastre seu interesse. A Arena pode reservar temporariamente a vaga para você quando houver cancelamento.</p></div></div>
<form method="post" action="/arena/<?=$e($routeSlug)?>/waitlist" class="row g-2"><?=CSRF::field()?>
<div class="col-md-4"><input class="form-control" name="name" required placeholder="Nome"></div><div class="col-md-4"><input class="form-control" name="phone" required placeholder="WhatsApp"></div><div class="col-md-4"><input class="form-control" type="email" name="email" placeholder="E-mail"></div>
<div class="col-md-3"><select class="form-select" name="modality_id"><option value="">Qualquer modalidade</option><?php foreach($modalities as $m):?><option value="<?=(int)$m['id']?>"><?=$e($m['name'])?></option><?php endforeach;?></select></div>
<div class="col-md-3"><select class="form-select" name="court_id"><option value="">Qualquer quadra</option><?php foreach($courts as $c):?><option value="<?=(int)$c['id']?>"><?=$e($c['name'])?></option><?php endforeach;?></select></div>
<div class="col-md-2"><input class="form-control" type="date" min="<?=$today?>" name="preferred_date" value="<?=$today?>" required></div><div class="col-md-2"><input class="form-control" type="time" name="preferred_start" title="Horário preferido"></div><div class="col-md-2"><select class="form-select" name="flexibility_minutes"><option value="0">Horário exato</option><option value="30">± 30 min</option><option value="60">± 1 hora</option><option value="120">± 2 horas</option></select></div>
<input type="hidden" name="duration_minutes" value="60">
<div class="col-12 d-flex flex-wrap gap-3"><label class="form-check"><input class="form-check-input" type="checkbox" name="notify_whatsapp" value="1"> Quero receber esta oferta por WhatsApp</label><label class="form-check"><input class="form-check-input" type="checkbox" name="notify_email" value="1"> Quero receber esta oferta por e-mail</label></div>
<div class="col-12"><button class="btn btn-outline-primary">Entrar na lista de espera</button></div></form></div></section>
<?php endif;?>
<?php if(!empty($arenaSettings['amenities_json'])):$amenities=json_decode($arenaSettings['amenities_json'],true)?:[]; if($amenities):?><section class="card border-0 shadow-sm mt-4"><div class="card-body"><h2 class="h5">Comodidades</h2><div class="d-flex flex-wrap gap-2"><?php foreach($amenities as $a):?><span class="badge text-bg-light"><?=$e(str_replace('_',' ',$a))?></span><?php endforeach;?></div></div></section><?php endif;endif;?>
<script src="/public/assets/js/sports-public.js?v=4-arena-v2"></script>
