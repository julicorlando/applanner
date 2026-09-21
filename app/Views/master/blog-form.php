<?php
$e=fn($v)=>htmlspecialchars((string)$v,ENT_QUOTES,'UTF-8');
$editing=!empty($post);
?>
<div class="section-heading">
 <div><div class="eyebrow">Blog</div><h1><?=$editing?'Editar artigo':'Novo artigo'?></h1></div>
 <a class="btn btn-light" href="/master/blog">Voltar</a>
</div>
<form method="post" enctype="multipart/form-data" action="<?=$editing?'/master/blog/'.(int)$post['id']:'/master/blog'?>" data-warn-unsaved>
 <?=\App\Core\CSRF::field()?>
 <div class="row g-4">
  <div class="col-xl-8"><div class="card"><div class="card-body">
   <div class="mb-3"><label class="form-label">Título</label><input class="form-control" name="title" maxlength="180" required value="<?=$e($post['title']??'')?>"></div>
   <div class="mb-3"><label class="form-label">Resumo para a listagem</label><textarea class="form-control" name="excerpt" maxlength="320" rows="3" required><?=$e($post['excerpt']??'')?></textarea></div>
   <div><label class="form-label">Conteúdo</label><textarea class="form-control blog-editor" name="content" rows="18" required placeholder="Separe os parágrafos com uma linha em branco."><?=$e($post['content']??'')?></textarea><div class="form-text">O texto é publicado com parágrafos preservados e proteção contra código malicioso.</div></div>
  </div></div></div>
  <div class="col-xl-4">
   <div class="card mb-4"><div class="card-header"><strong>Publicação</strong></div><div class="card-body">
    <label class="form-label">Status</label><select class="form-select mb-3" name="status"><option value="draft" <?=($post['status']??'draft')==='draft'?'selected':''?>>Rascunho</option><option value="published" <?=($post['status']??'')==='published'?'selected':''?>>Publicado</option><option value="archived" <?=($post['status']??'')==='archived'?'selected':''?>>Arquivado</option></select>
    <label class="form-check"><input class="form-check-input" type="checkbox" name="featured" value="1" <?=!empty($post['featured'])?'checked':''?>> Destacar este artigo</label>
    <button class="btn btn-primary w-100 mt-4">Salvar artigo</button>
    <?php if($editing&&$post['status']==='published'):?><a class="btn btn-light w-100 mt-2" target="_blank" href="/blog/<?=$e($post['slug'])?>">Visualizar</a><?php endif;?>
   </div></div>
   <div class="card mb-4"><div class="card-header"><strong>Capa</strong></div><div class="card-body">
    <?php if(!empty($post['cover_path'])):?><img class="blog-cover-preview" src="<?=$e($post['cover_path'])?>" alt=""><label class="form-check mt-2"><input class="form-check-input" type="checkbox" name="remove_cover" value="1"> Remover capa</label><?php endif;?>
    <input class="form-control mt-2" type="file" name="cover" accept="image/jpeg,image/png,image/webp"><div class="form-text">Recomendado: 1400 × 800 px.</div>
   </div></div>
   <div class="card"><div class="card-header"><strong>Endereço e SEO</strong></div><div class="card-body">
    <label class="form-label">Slug</label><input class="form-control mb-3" name="slug" value="<?=$e($post['slug']??'')?>" placeholder="gerado-pelo-titulo">
    <label class="form-label">Título SEO</label><input class="form-control mb-3" name="meta_title" maxlength="180" value="<?=$e($post['meta_title']??'')?>">
    <label class="form-label">Descrição SEO</label><textarea class="form-control" name="meta_description" maxlength="320" rows="3"><?=$e($post['meta_description']??'')?></textarea>
   </div></div>
   <?php if($editing):?><button class="btn btn-outline-danger mt-3" type="submit" formaction="/master/blog/<?=(int)$post['id']?>/excluir" formnovalidate onclick="return confirm('Excluir definitivamente este artigo?')">Excluir artigo</button><?php endif;?>
  </div>
 </div>
</form>
