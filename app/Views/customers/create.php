<h1 class="h3 mb-3">Novo cliente</h1>
<div class="card border-0 shadow-sm"><div class="card-body">
<form method="post" action="/customers/store">
<?= \App\Core\CSRF::field() ?>
<div class="row g-3">
<div class="col-md-6"><label class="form-label">Nome</label><input name="name" class="form-control" required maxlength="150"></div>
<div class="col-md-3"><label class="form-label">WhatsApp</label><input name="phone" class="form-control" maxlength="30"></div>
<div class="col-md-3"><label class="form-label">E-mail</label><input name="email" type="email" class="form-control" maxlength="190"></div>
</div>
<div class="mt-3"><button class="btn btn-primary">Salvar</button> <a class="btn btn-light" href="/customers">Cancelar</a></div>
</form></div></div>
