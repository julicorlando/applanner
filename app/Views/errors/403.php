<div class="row justify-content-center py-5"><div class="col-lg-6 text-center">
<div class="display-1 fw-bold text-danger">403</div><h1 class="h3">Acesso negado</h1>
<p class="text-secondary"><?= htmlspecialchars($message ?? 'Você não possui permissão para acessar esta área.', ENT_QUOTES, 'UTF-8') ?></p>
<a class="btn btn-primary" href="/dashboard">Voltar ao painel</a>
</div></div>
