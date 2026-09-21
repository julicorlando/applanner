<div class="row justify-content-center">
  <div class="col-md-5 col-lg-4">
    <div class="card shadow-sm border-0 mt-5">
      <div class="card-body p-4">
        <h1 class="h4 mb-3">Entrar</h1>
        <?php if (!empty($error)): ?>
          <div class="alert alert-danger"><?= htmlspecialchars($error, ENT_QUOTES, 'UTF-8') ?></div>
        <?php endif; ?>
        <form method="post" action="/login" autocomplete="off">
          <?= \App\Core\CSRF::field() ?>
          <div class="mb-3">
            <label class="form-label">E-mail</label>
            <input class="form-control" type="email" name="email" required maxlength="190" autocomplete="username">
          </div>
          <div class="mb-3">
            <label class="form-label">Senha</label>
            <input class="form-control" type="password" name="password" required autocomplete="current-password">
          </div>
          <button class="btn btn-primary w-100">Entrar</button>
          <a class="btn btn-link w-100 mt-2" href="/forgot-password">Esqueci minha senha</a>
        </form><div class="text-center mt-3"><a href="/profissional/login">Sou profissional</a></div>
      </div>
    </div>
  </div>
</div>
