<div class="row justify-content-center"><div class="col-md-6 col-lg-4"><div class="card shadow-sm border-0 mt-5"><div class="card-body p-4">
<h1 class="h4 mb-3">Definir nova senha</h1><?php if($error): ?><div class="alert alert-danger"><?= htmlspecialchars($error,ENT_QUOTES,'UTF-8') ?></div><?php endif; ?>
<form method="post" action="/reset-password"><?= \App\Core\CSRF::field() ?><input type="hidden" name="token" value="<?= htmlspecialchars($token,ENT_QUOTES,'UTF-8') ?>">
<label class="form-label">Nova senha</label><input class="form-control" type="password" name="password" minlength="12" required autocomplete="new-password"><div class="form-text">12+ caracteres, maiúscula, minúscula, número e símbolo.</div>
<label class="form-label mt-3">Confirmar senha</label><input class="form-control" type="password" name="password_confirmation" minlength="12" required autocomplete="new-password"><button class="btn btn-primary w-100 mt-3">Alterar senha</button></form>
</div></div></div></div>
