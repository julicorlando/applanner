<?php use App\Core\CSRF; ?>
<div class="sports-head">
  <div><span class="sports-kicker">MÓDULO INDEPENDENTE</span><h1>Bancos e Pagamentos</h1><p>Conecte somente provedores homologados. O ApPlanner nunca solicita senha de internet banking, PIN ou CVV.</p></div>
  <a class="btn btn-outline-secondary" href="/sports">Voltar à Arena</a>
</div>
<?php if(isset($_GET['connected'])):?><div class="alert alert-success">Integração validada e conectada.</div><?php endif;?>
<?php if(isset($_GET['disconnected'])):?><div class="alert alert-secondary">Integração desconectada e credenciais removidas.</div><?php endif;?>

<div class="row g-4">
  <div class="col-xl-5">
    <div class="card border-0 shadow-sm"><div class="card-body">
      <h2 class="h5">Conectar instituição financeira</h2>
      <p class="text-secondary">Somente integrações realmente disponíveis podem ser ativadas.</p><div class="alert alert-light border small"><strong>Webhook da Arena</strong><br><code class="text-break"><?=htmlspecialchars($webhookUrl,ENT_QUOTES,'UTF-8')?></code><br><span class="text-secondary">Cadastre esta URL no painel do Mercado Pago. Este endpoint é separado da cobrança da assinatura SaaS do ApPlanner.</span></div>
      <div class="d-grid gap-3">
      <?php foreach($providers as $slug=>$provider): ?>
        <div class="border rounded-4 p-3">
          <div class="d-flex justify-content-between gap-3"><strong><?=htmlspecialchars($provider['name'])?></strong><span class="badge <?=$provider['available']?'text-bg-success':'text-bg-secondary'?>"><?=$provider['available']?'Disponível':'Ainda não disponível'?></span></div>
          <small class="text-secondary d-block mt-2"><?=htmlspecialchars($provider['note'])?></small>
          <?php if($provider['available'] && $canManage): ?>
          <details class="mt-3"><summary class="btn btn-sm btn-outline-primary">Configurar</summary>
            <form class="mt-3" method="post" action="/settings/banking/connect" autocomplete="off">
              <?=CSRF::field()?><input type="hidden" name="provider" value="<?=htmlspecialchars($slug)?>">
              <label class="form-label">Ambiente</label><select class="form-select mb-2" name="environment"><option value="sandbox">Sandbox / Teste</option><option value="production">Produção</option></select>
              <label class="form-label">Public Key</label><input class="form-control mb-2" name="public_key" required autocomplete="off" placeholder="APP_USR-... / TEST-..."><small class="text-secondary d-block mb-2">Usada apenas no navegador para tokenizar o cartão; não é uma senha.</small><label class="form-label">Access Token</label><input class="form-control mb-2" type="password" name="access_token" required autocomplete="new-password" placeholder="TEST-... ou APP_USR-...">
              <label class="form-label">Segredo do webhook</label><input class="form-control mb-2" type="password" name="webhook_secret" minlength="16" required autocomplete="new-password">
              <div class="alert alert-info small">A conexão é validada diretamente na API oficial antes de ser salva. As credenciais são criptografadas e não voltam a ser exibidas.</div>
              <button class="btn btn-primary w-100">Validar e conectar</button>
            </form>
          </details>
          <?php endif; ?>
        </div>
      <?php endforeach; ?>
      </div>
    </div></div>
  </div>
  <div class="col-xl-7">
    <div class="card border-0 shadow-sm mb-4"><div class="card-body"><h2 class="h5">Conexões</h2>
      <?php if(!$connections):?><div class="sports-empty">Nenhuma integração conectada.</div><?php endif;?>
      <?php foreach($connections as $c):?><div class="sports-list-row"><span><strong><?=htmlspecialchars($c['display_name'])?> · <?=htmlspecialchars(ucfirst($c['environment']))?></strong><small>Status: <?=htmlspecialchars($c['status'])?><?php if($c['last_tested_at']):?> · testado em <?=date('d/m/Y H:i',strtotime($c['last_tested_at']))?><?php endif;?></small></span><?php if($canManage && $c['status']!=='disabled'):?><form method="post" action="/settings/banking/connection/<?=(int)$c['id']?>/disconnect" onsubmit="return confirm('Desconectar esta integração?')"><?=CSRF::field()?><button class="btn btn-sm btn-outline-danger">Desconectar</button></form><?php endif;?></div><?php endforeach;?>
    </div></div>
    <?php if($transactions):?><div class="card border-0 shadow-sm"><div class="card-body"><h2 class="h5">Conciliação recente</h2><div class="table-responsive"><table class="table align-middle"><thead><tr><th>Referência</th><th>Método</th><th>Bruto</th><th>Líquido</th><th>Status</th><th>Data</th></tr></thead><tbody><?php foreach($transactions as $tx):?><tr><td><?=htmlspecialchars($tx['reference_type'])?> #<?=(int)$tx['reference_id']?></td><td><?=htmlspecialchars(strtoupper($tx['method']))?></td><td>R$ <?=number_format((float)$tx['gross_amount'],2,',','.')?></td><td>R$ <?=number_format((float)$tx['net_amount'],2,',','.')?></td><td><span class="sports-status status-<?=htmlspecialchars($tx['status'])?>"><?=htmlspecialchars($tx['status'])?></span></td><td><?=date('d/m/Y H:i',strtotime($tx['created_at']))?></td></tr><?php endforeach;?></tbody></table></div></div></div><?php endif;?>
  </div>
</div>
