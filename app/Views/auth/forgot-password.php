<div class="row justify-content-center"><div class="col-md-6 col-lg-4"><div class="card shadow-sm border-0 mt-5"><div class="card-body p-4">
<h1 class="h4 mb-2">Recuperar senha</h1><p class="text-secondary small">Enviaremos um link com validade de 30 minutos.</p>
<?php if($message): ?><div class="alert alert-success"><?= htmlspecialchars($message,ENT_QUOTES,'UTF-8') ?></div><?php endif; ?>
<form method="post" action="/forgot-password"><?= \App\Core\CSRF::field() ?><label class="form-label">E-mail</label><input class="form-control" type="email" name="email" required autocomplete="email"><button class="btn btn-primary w-100 mt-3">Enviar instruções</button></form>
<a class="btn btn-link w-100 mt-2" href="/login">Voltar ao login</a>
</div></div></div></div>
