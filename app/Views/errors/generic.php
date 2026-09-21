<section class="container py-5" style="max-width:760px">
  <div class="card shadow-sm border-0">
    <div class="card-body p-4 p-md-5 text-center">
      <div class="display-4 fw-semibold mb-3"><?=htmlspecialchars((string)($status ?? 'Erro'), ENT_QUOTES, 'UTF-8')?></div>
      <h1 class="h3 mb-3"><?=htmlspecialchars((string)($title ?? 'Não foi possível concluir'), ENT_QUOTES, 'UTF-8')?></h1>
      <p class="text-secondary mb-4"><?=htmlspecialchars((string)($message ?? 'Não conseguimos concluir esta solicitação.'), ENT_QUOTES, 'UTF-8')?></p>
      <a href="javascript:history.back()" class="btn btn-outline-secondary me-2">Voltar</a>
      <a href="/dashboard" class="btn btn-primary">Ir ao início</a>
    </div>
  </div>
</section>
