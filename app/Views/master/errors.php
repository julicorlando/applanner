<?php $catalog=\App\Services\ErrorKnowledgeBase::all(); ?>
<div class="section-heading"><div><div class="eyebrow">Diagnóstico e suporte</div><h1>Central de erros</h1><p class="text-secondary mb-0">Consulte ocorrências reais do servidor e a base de causas e soluções do ApPlanner.</p></div></div>

<form method="get" class="card p-3 mb-4">
 <div class="d-flex gap-2 flex-wrap">
  <input class="form-control flex-grow-1" style="min-width:240px" name="q" value="<?=htmlspecialchars($search)?>" placeholder="ERR-20260807-87D8B9, 402, SMTP, SQLSTATE...">
  <button class="btn btn-primary">Pesquisar nos registros</button>
  <?php if($search):?><a class="btn btn-outline-secondary" href="/master/errors">Limpar</a><?php endif;?>
 </div>
</form>

<div class="card mb-4">
 <div class="card-header"><strong>Ocorrências registradas no servidor</strong><div class="text-secondary small">Detalhes técnicos recentes do storage/logs/app.log</div></div>
 <div class="table-responsive"><table class="table mb-0"><thead><tr><th>Data</th><th>Error ID</th><th>Mensagem</th><th>Origem</th></tr></thead><tbody>
 <?php foreach($rows as $r):?><tr><td><?=htmlspecialchars($r['at'])?></td><td><code><?=htmlspecialchars($r['id'])?></code></td><td><strong><?=htmlspecialchars($r['message'])?></strong></td><td><code><?=htmlspecialchars(basename($r['file']).':'.$r['line'])?></code><details class="mt-2"><summary>Detalhes técnicos</summary><pre class="small text-wrap mt-2"><?=htmlspecialchars($r['raw'])?></pre></details></td></tr><?php endforeach;?>
 <?php if(!$rows):?><tr><td colspan="4" class="empty-state"><?=$search?'Código não encontrado no app.log deste servidor.':'Nenhum erro interno registrado.'?></td></tr><?php endif;?>
 </tbody></table></div>
</div>

<div class="section-heading"><div><div class="eyebrow">Base de conhecimento</div><h2>Guia de códigos, causas e soluções</h2><p class="text-secondary mb-0">Use a busca abaixo durante o atendimento. Nenhuma ação é executada automaticamente.</p></div></div>
<div class="card p-3 mb-3"><input id="kb-search" class="form-control" type="search" placeholder="Filtrar por código, categoria, causa ou solução..."></div>
<div class="table-responsive card"><table class="table align-middle mb-0" id="kb-table"><thead><tr><th style="min-width:160px">Código/erro</th><th style="min-width:140px">Área</th><th style="min-width:190px">Significado</th><th style="min-width:260px">Possíveis causas</th><th style="min-width:300px">Solução recomendada</th></tr></thead><tbody>
<?php foreach($catalog as $item):?><tr class="kb-row"><td><code><?=htmlspecialchars($item['code'])?></code></td><td><span class="badge text-bg-light"><?=htmlspecialchars($item['category'])?></span></td><td><strong><?=htmlspecialchars($item['title'])?></strong></td><td><?=htmlspecialchars($item['cause'])?></td><td><?=htmlspecialchars($item['solution'])?></td></tr><?php endforeach;?>
<tr id="kb-empty" hidden><td colspan="5" class="empty-state">Nenhum item corresponde à pesquisa.</td></tr>
</tbody></table></div>
<script>
(()=>{const input=document.getElementById('kb-search'),rows=[...document.querySelectorAll('.kb-row')],empty=document.getElementById('kb-empty');if(!input)return;input.addEventListener('input',()=>{const term=input.value.toLocaleLowerCase('pt-BR').trim();let shown=0;rows.forEach(row=>{const ok=!term||row.textContent.toLocaleLowerCase('pt-BR').includes(term);row.hidden=!ok;if(ok)shown++;});empty.hidden=shown!==0;});})();
</script>
