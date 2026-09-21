<h1 class="h3 mb-3">Novo serviço</h1>
<div class="card border-0 shadow-sm"><div class="card-body">
<form method="post" action="/services/store">
<?= \App\Core\CSRF::field() ?>
<div class="row g-3">
<div class="col-md-6"><label class="form-label">Nome</label><input name="name" class="form-control" required maxlength="150"></div>
<div class="col-md-3"><label class="form-label">Duração (min)</label><input name="duration_minutes" type="number" min="5" max="1440" value="30" class="form-control" required></div>
<div class="col-md-3"><label class="form-label">Preço</label><input name="price" type="number" step="0.01" min="0" class="form-control" required></div>
</div>
<div class="mt-3"><button class="btn btn-primary">Salvar</button> <a class="btn btn-light" href="/services">Cancelar</a></div>
</form></div></div>
