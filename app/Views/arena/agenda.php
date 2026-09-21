<?php
$days=[];
if($viewMode==='week'){for($d=$periodStart;$d<$periodEnd;$d=$d->modify('+1 day'))$days[]=$d;}else{$days[]=$periodStart;}
$statusLabels=['pending_payment'=>'Aguard. pagamento','confirmed'=>'Reservada','completed'=>'Concluída','no_show'=>'No-show'];
?>
<div class="sports-head"><div><span class="sports-kicker">APPLANNER ARENA</span><h1>Agenda visual</h1><p>Quadras nas colunas, horários e ocupações em uma visão operacional.</p></div><div class="d-flex gap-2 flex-wrap"><a href="/sports/reservations" class="btn btn-primary">+ Nova reserva</a><a href="/sports/courts" class="btn btn-outline-primary">Quadras/Espaços</a></div></div>
<form class="card border-0 shadow-sm mb-4"><div class="card-body d-flex flex-wrap gap-2 align-items-end"><div><label class="form-label">Data</label><input class="form-control" type="date" name="date" value="<?=htmlspecialchars($date)?>"></div><div><label class="form-label">Visão</label><select class="form-select" name="view"><option value="day" <?=$viewMode==='day'?'selected':''?>>Dia</option><option value="week" <?=$viewMode==='week'?'selected':''?>>Semana</option></select></div><button class="btn btn-outline-primary">Atualizar</button></div></form>
<?php foreach($days as $day): $dayKey=$day->format('Y-m-d');?>
<div class="card border-0 shadow-sm mb-4"><div class="card-body"><h2 class="h5 mb-3"><?=$day->format('d/m/Y')?> · <?=['Sunday'=>'Domingo','Monday'=>'Segunda','Tuesday'=>'Terça','Wednesday'=>'Quarta','Thursday'=>'Quinta','Friday'=>'Sexta','Saturday'=>'Sábado'][$day->format('l')]??$day->format('l')?></h2>
<div class="table-responsive arena-calendar"><table class="table table-bordered align-middle"><thead><tr><th class="arena-time-col">Horário</th><?php foreach($courts as $court):?><th><?=htmlspecialchars($court['name'])?></th><?php endforeach;?></tr></thead><tbody>
<?php for($hour=6;$hour<=23;$hour++): foreach([0,30] as $minute): if($hour===23&&$minute===30)continue; $slot=sprintf('%02d:%02d',$hour,$minute); $slotStart=new DateTimeImmutable($dayKey.' '.$slot.':00'); $slotEnd=$slotStart->modify('+30 minutes'); ?>
<tr><th class="arena-time-col"><?=$slot?></th><?php foreach($courts as $court):
$items=array_values(array_filter($reservations,fn($r)=>(int)$r['court_id']===(int)$court['id'] && new DateTimeImmutable($r['starts_at'])<$slotEnd && new DateTimeImmutable($r['ends_at'])>$slotStart));
$blocked=array_values(array_filter($blocks,fn($b)=>(int)$b['court_id']===(int)$court['id'] && new DateTimeImmutable($b['starts_at'])<$slotEnd && new DateTimeImmutable($b['ends_at'])>$slotStart)); ?>
<td class="arena-slot <?= $items?'is-reserved':($blocked?'is-blocked':'is-free') ?>"><?php if($items): $r=$items[0];?><a href="/sports/reservations?from=<?=$dayKey?>&to=<?=$dayKey?>"><strong><?=htmlspecialchars($r['customer_name'])?></strong><small><?=date('H:i',strtotime($r['starts_at']))?>–<?=date('H:i',strtotime($r['ends_at']))?> · <?=htmlspecialchars($statusLabels[$r['status']]??$r['status'])?></small></a><?php elseif($blocked):?><strong>Bloqueada</strong><small><?=htmlspecialchars($blocked[0]['reason']??'Indisponível')?></small><?php else:?><a href="/sports/reservations?starts_at=<?=rawurlencode($slotStart->format('Y-m-d\TH:i'))?>&court_id=<?=(int)$court['id']?>"><span>Livre</span></a><?php endif;?></td>
<?php endforeach;?></tr>
<?php endforeach; endfor; ?>
</tbody></table></div></div></div>
<?php endforeach;?>
