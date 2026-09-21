<?php
$shareUrl=urlencode(((!empty($_SERVER['HTTPS'])&&$_SERVER['HTTPS']!=='off')?'https':'http').'://'.($_SERVER['HTTP_HOST']??'applanner.com.br').($_SERVER['REQUEST_URI']??('/blog/'.$post['slug'])));
$shareTitle=urlencode($post['title'].' | Blog ApPlanner');
$shareText=urlencode($post['title'].' — '.$post['excerpt']);
?>
<article class="blog-article">
 <a href="/blog">← Voltar ao blog</a>
 <header><span class="public-kicker">Blog ApPlanner</span><h1><?=htmlspecialchars($post['title'])?></h1><p><?=htmlspecialchars($post['excerpt'])?></p><small>Publicado em <?=date('d/m/Y',strtotime($post['published_at']))?> · por <?=htmlspecialchars($post['author_name'])?></small></header>
 <?php if($post['cover_path']):?><img class="blog-article-cover" src="<?=htmlspecialchars($post['cover_path'])?>" alt="<?=htmlspecialchars($post['title'])?>"><?php endif;?>
 <div class="blog-article-content"><?=nl2br(htmlspecialchars($post['content'],ENT_QUOTES,'UTF-8'))?></div>
 <section class="blog-share" aria-labelledby="shareTitle"><div><span class="eyebrow">Compartilhe</span><h2 id="shareTitle">Gostou deste conteúdo?</h2><p>Envie para alguém que também deseja organizar e fazer o negócio crescer.</p></div><div class="share-buttons">
  <a class="share-button whatsapp" target="_blank" rel="noopener noreferrer" href="https://wa.me/?text=<?=$shareText?>%20<?=$shareUrl?>" aria-label="Compartilhar no WhatsApp">WhatsApp</a>
  <a class="share-button facebook" target="_blank" rel="noopener noreferrer" href="https://www.facebook.com/sharer/sharer.php?u=<?=$shareUrl?>" aria-label="Compartilhar no Facebook">Facebook</a>
  <a class="share-button linkedin" target="_blank" rel="noopener noreferrer" href="https://www.linkedin.com/sharing/share-offsite/?url=<?=$shareUrl?>" aria-label="Compartilhar no LinkedIn">LinkedIn</a>
  <a class="share-button x" target="_blank" rel="noopener noreferrer" href="https://twitter.com/intent/tweet?text=<?=$shareTitle?>&url=<?=$shareUrl?>" aria-label="Compartilhar no X">X</a>
  <a class="share-button telegram" target="_blank" rel="noopener noreferrer" href="https://t.me/share/url?url=<?=$shareUrl?>&text=<?=$shareTitle?>" aria-label="Compartilhar no Telegram">Telegram</a>
  <a class="share-button email" href="mailto:?subject=<?=$shareTitle?>&body=<?=$shareText?>%0A%0A<?=$shareUrl?>" aria-label="Compartilhar por e-mail">E-mail</a>
  <button class="share-button native" type="button" data-native-share data-share-title="<?=htmlspecialchars($post['title'],ENT_QUOTES,'UTF-8')?>" data-share-text="<?=htmlspecialchars($post['excerpt'],ENT_QUOTES,'UTF-8')?>">Compartilhar</button>
 </div></section>
 <footer><h2>Coloque essas ideias em prática.</h2><p>Organize sua operação e ofereça uma experiência de agendamento melhor com o ApPlanner.</p><a class="btn btn-primary btn-lg" href="/cadastro">Começar teste grátis</a></footer>
</article>
