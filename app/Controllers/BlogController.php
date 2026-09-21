<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,HttpException,View};

final class BlogController
{
    public function index():void
    {
        $pdo=Database::connection();$featured=$pdo->query("SELECT * FROM blog_posts WHERE status='published' ORDER BY featured DESC,published_at DESC LIMIT 1")->fetch();$skip=(int)($featured['id']??0);$q=$pdo->prepare("SELECT * FROM blog_posts WHERE status='published' AND id<>:skip ORDER BY published_at DESC LIMIT 24");$q->execute(['skip'=>$skip]);View::render('blog/index',['title'=>'Blog ApPlanner','featured'=>$featured,'posts'=>$q->fetchAll(),'publicLayout'=>true]);
    }
    public function show(string $slug):void
    {
        $q=Database::connection()->prepare("SELECT p.*,u.name author_name FROM blog_posts p JOIN users u ON u.id=p.author_id WHERE p.slug=:slug AND p.status='published' LIMIT 1");$q->execute(['slug'=>$slug]);$post=$q->fetch();if(!$post)HttpException::abort(404,'Artigo não encontrado.');View::render('blog/show',['title'=>$post['meta_title']?:$post['title'],'post'=>$post,'publicLayout'=>true]);
    }
    public function master():void
    {
        Auth::requireRole('master');$posts=Database::connection()->query('SELECT p.*,u.name author_name FROM blog_posts p JOIN users u ON u.id=p.author_id ORDER BY p.created_at DESC')->fetchAll();View::render('master/blog-index',['title'=>'Blog','posts'=>$posts]);
    }
    public function create():void{Auth::requireRole('master');View::render('master/blog-form',['title'=>'Novo artigo','post'=>null]);}
    public function edit(string $id):void{Auth::requireRole('master');$q=Database::connection()->prepare('SELECT * FROM blog_posts WHERE id=:id');$q->execute(['id'=>(int)$id]);$post=$q->fetch();if(!$post)HttpException::abort(404,'Artigo não encontrado.');View::render('master/blog-form',['title'=>'Editar artigo','post'=>$post]);}
    public function save(?string $id=null):void
    {
        Auth::requireRole('master');CSRF::enforce();$pdo=Database::connection();$post=null;
        if($id!==null){$q=$pdo->prepare('SELECT * FROM blog_posts WHERE id=:id');$q->execute(['id'=>(int)$id]);$post=$q->fetch();if(!$post)HttpException::abort(404,'Artigo não encontrado.');}
        $title=trim((string)($_POST['title']??''));$excerpt=trim((string)($_POST['excerpt']??''));$content=trim((string)($_POST['content']??''));
        if(mb_strlen($title)<5||mb_strlen($excerpt)<20||mb_strlen($content)<80)HttpException::abort(422,'Preencha título, resumo e conteúdo completo.');
        $slug=$this->uniqueSlug($pdo,(string)(($_POST['slug']??'')?:$title),(int)($post['id']??0));$status=in_array($_POST['status']??'', ['draft','published','archived'],true)?$_POST['status']:'draft';$cover=$post['cover_path']??null;
        if(!empty($_FILES['cover']['name'])){$cover=$this->upload($_FILES['cover']);if(!empty($post['cover_path'])&&$post['cover_path']!==$cover)$this->deleteCover($post['cover_path']);}
        if(isset($_POST['remove_cover'])){$this->deleteCover((string)$cover);$cover=null;}
        $params=['title'=>$title,'slug'=>$slug,'excerpt'=>mb_substr($excerpt,0,320),'content'=>$content,'cover'=>$cover,'status'=>$status,'featured'=>isset($_POST['featured'])?1:0,'meta_title'=>mb_substr(trim((string)($_POST['meta_title']??'')),0,180)?:null,'meta_description'=>mb_substr(trim((string)($_POST['meta_description']??'')),0,320)?:null];
        if($params['featured'])$pdo->exec('UPDATE blog_posts SET featured=0');
        if($post){$params['id']=$post['id'];$params['publish_status']=$status;$pdo->prepare("UPDATE blog_posts SET title=:title,slug=:slug,excerpt=:excerpt,content=:content,cover_path=:cover,status=:status,featured=:featured,meta_title=:meta_title,meta_description=:meta_description,published_at=CASE WHEN :publish_status='published' THEN COALESCE(published_at,NOW()) ELSE published_at END,updated_at=NOW() WHERE id=:id")->execute($params);$postId=(int)$post['id'];}
        else{$params['author']=Auth::user()['id'];$params['published']=$status==='published'?date('Y-m-d H:i:s'):null;$pdo->prepare('INSERT INTO blog_posts(title,slug,excerpt,content,cover_path,status,featured,meta_title,meta_description,author_id,published_at,created_at,updated_at)VALUES(:title,:slug,:excerpt,:content,:cover,:status,:featured,:meta_title,:meta_description,:author,:published,NOW(),NOW())')->execute($params);$postId=(int)$pdo->lastInsertId();}
        Audit::log($post?'BLOG_POST_UPDATED':'BLOG_POST_CREATED','blog_posts',$postId,$post?:null,['title'=>$title,'status'=>$status]);header('Location: /master/blog/'.$postId.'/editar');exit;
    }
    public function delete(string $id):void{Auth::requireRole('master');CSRF::enforce();$pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM blog_posts WHERE id=:id');$q->execute(['id'=>(int)$id]);$post=$q->fetch();if(!$post)HttpException::abort(404,'Artigo não encontrado.');$pdo->prepare('DELETE FROM blog_posts WHERE id=:id')->execute(['id'=>$post['id']]);$this->deleteCover((string)$post['cover_path']);Audit::log('BLOG_POST_DELETED','blog_posts',(int)$id,$post);header('Location: /master/blog');exit;}
    private function uniqueSlug(\PDO $pdo,string $value,int $ignore):string{$ascii=iconv('UTF-8','ASCII//TRANSLIT//IGNORE',$value)?:$value;$base=trim(preg_replace('/[^a-z0-9]+/','-',mb_strtolower($ascii)),'-')?:'artigo';$slug=$base;$i=2;$q=$pdo->prepare('SELECT 1 FROM blog_posts WHERE slug=:slug AND id<>:id');do{$q->execute(['slug'=>$slug,'id'=>$ignore]);if(!$q->fetchColumn())return $slug;$slug=$base.'-'.$i++;}while($i<1000);throw new \RuntimeException('Não foi possível gerar o endereço do artigo.');}
    private function upload(array $file):string{if(($file['error']??UPLOAD_ERR_NO_FILE)!==UPLOAD_ERR_OK||(int)$file['size']>5*1024*1024)throw new \DomainException('Capa inválida ou maior que 5 MB.');$info=@getimagesize($file['tmp_name']);$allowed=['image/jpeg'=>'jpg','image/png'=>'png','image/webp'=>'webp'];if(!isset($allowed[$info['mime']??'']))throw new \DomainException('Use uma capa JPG, PNG ou WebP.');$dir=dirname(__DIR__,2).'/public/uploads/blog';if(!is_dir($dir)&&!mkdir($dir,0755,true))throw new \RuntimeException('Não foi possível criar a pasta do blog.');$name=bin2hex(random_bytes(18)).'.'.$allowed[$info['mime']];if(!move_uploaded_file($file['tmp_name'],$dir.'/'.$name))throw new \RuntimeException('Falha ao salvar a capa.');return '/public/uploads/blog/'.$name;}
    private function deleteCover(string $path):void{if(!str_starts_with($path,'/public/uploads/blog/'))return;$file=dirname(__DIR__,2).$path;if(is_file($file))@unlink($file);}
}
