<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,HttpException,View};
use App\Services\{LegalDocumentService,PlatformSetting};

final class LegalController
{
    public function terms():void{$this->publicDoc('terms','Termos de Uso');}
    public function privacy():void{$this->publicDoc('privacy','Política de Privacidade');}

    private function publicDoc(string $type,string $title):void
    {
        $doc=LegalDocumentService::current($type);if(!$doc)HttpException::abort(404,'Documento não publicado.');
        View::render('legal/public',['title'=>$title,'doc'=>$doc,'content'=>LegalDocumentService::rendered($doc),'publicLayout'=>true]);
    }

    public function acceptance():void
    {
        Auth::requireLogin();if(Auth::isPlatformStaff()){header('Location: /master');exit;}
        $pending=LegalDocumentService::pendingForUser((int)Auth::user()['id']);
        View::render('legal/acceptance',['title'=>'Atualização dos documentos legais','pending'=>$pending]);
    }

    public function accept():void
    {
        Auth::requireLogin();CSRF::enforce();if(!isset($_POST['accept']))HttpException::abort(422,'Confirme o aceite para continuar.');
        LegalDocumentService::acceptCurrent((int)Auth::user()['id'],Auth::user()['tenant_id']?:(null));
        Audit::log('legal.accepted','legal_documents',null,null,['current'=>true]);header('Location: /dashboard');exit;
    }

    public function masterIndex():void
    {
        Auth::requireRole('master');LegalDocumentService::ensureDefaults();$pdo=Database::connection();
        $docs=$pdo->query("SELECT ld.*,(SELECT COUNT(*) FROM legal_acceptances la WHERE la.document_id=ld.id) acceptances FROM legal_documents ld ORDER BY FIELD(type,'terms','privacy'),created_at DESC")->fetchAll();
        $settings=['legal_name'=>PlatformSetting::get('legal.legal_name',''),'document'=>PlatformSetting::get('legal.document',''),'support_email'=>PlatformSetting::get('legal.support_email',''),'privacy_email'=>PlatformSetting::get('legal.privacy_email',''),'address'=>PlatformSetting::get('legal.address',''),'foro'=>PlatformSetting::get('legal.foro','')];
        $acceptances=$pdo->query("SELECT la.accepted_at,la.ip_address,ld.type,ld.version,u.name user_name,u.email,t.name tenant_name FROM legal_acceptances la JOIN legal_documents ld ON ld.id=la.document_id JOIN users u ON u.id=la.user_id LEFT JOIN tenants t ON t.id=la.tenant_id ORDER BY la.accepted_at DESC LIMIT 100")->fetchAll();View::render('master/legal-documents',['title'=>'Documentos legais','docs'=>$docs,'settings'=>$settings,'acceptances'=>$acceptances]);
    }

    public function saveSettings():void
    {
        Auth::requireRole('master');CSRF::enforce();
        $values=[];foreach(['legal_name','document','support_email','privacy_email','address','foro'] as $k)$values[$k]=trim((string)($_POST[$k]??''));if(strlen($values['legal_name'])<2||strlen($values['document'])<5||!filter_var($values['support_email'],FILTER_VALIDATE_EMAIL)||!filter_var($values['privacy_email'],FILTER_VALIDATE_EMAIL)||strlen($values['address'])<5||strlen($values['foro'])<2)HttpException::abort(422,'Preencha corretamente a identificação jurídica, os e-mails, endereço e foro.');foreach($values as $k=>$v)PlatformSetting::set('legal.'.$k,$v,false);
        Audit::log('MASTER_LEGAL_SETTINGS_UPDATED','settings');header('Location: /master/documentos-legais');exit;
    }

    public function edit(string $id):void
    {
        Auth::requireRole('master');LegalDocumentService::ensureDefaults();$q=Database::connection()->prepare('SELECT * FROM legal_documents WHERE id=:id');$q->execute(['id'=>(int)$id]);$doc=$q->fetch();if(!$doc)HttpException::abort(404,'Documento não encontrado.');View::render('master/legal-document-form',['title'=>'Editar documento legal','doc'=>$doc]);
    }

    public function update(string $id):void
    {
        Auth::requireRole('master');CSRF::enforce();$pdo=Database::connection();$q=$pdo->prepare("UPDATE legal_documents SET title=:title,content=:content,updated_at=NOW() WHERE id=:id AND status='draft'");$q->execute(['title'=>trim((string)($_POST['title']??'')),'content'=>trim((string)($_POST['content']??'')),'id'=>(int)$id]);if(!$q->rowCount())HttpException::abort(422,'Somente versões em rascunho podem ser editadas. Crie uma nova versão.');Audit::log('MASTER_LEGAL_DOCUMENT_UPDATED','legal_documents',(int)$id);header('Location: /master/documentos-legais/'.$id.'/editar');exit;
    }

    public function newVersion():void
    {
        Auth::requireRole('master');CSRF::enforce();$type=(string)($_POST['type']??'');$version=trim((string)($_POST['version']??''));if(!in_array($type,['terms','privacy'],true)||!preg_match('/^[0-9]+(?:\.[0-9]+){0,2}$/',$version))HttpException::abort(422,'Tipo ou versão inválida.');$current=LegalDocumentService::current($type);if(!$current)HttpException::abort(404,'Documento base não encontrado.');$q=Database::connection()->prepare("INSERT INTO legal_documents(type,version,title,content,status,created_by,created_at,updated_at)VALUES(:type,:version,:title,:content,'draft',:user,NOW(),NOW())");try{$q->execute(['type'=>$type,'version'=>$version,'title'=>$current['title'],'content'=>$current['content'],'user'=>Auth::user()['id']]);}catch(\PDOException $e){if($e->getCode()==='23000')HttpException::abort(422,'Esta versão já existe.');throw $e;}Audit::log('MASTER_LEGAL_VERSION_CREATED','legal_documents',(int)Database::connection()->lastInsertId(),null,['type'=>$type,'version'=>$version]);header('Location: /master/documentos-legais/'.Database::connection()->lastInsertId().'/editar');exit;
    }

    public function publish(string $id):void
    {
        Auth::requireRole('master');CSRF::enforce();$pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM legal_documents WHERE id=:id FOR UPDATE');$pdo->beginTransaction();try{$q->execute(['id'=>(int)$id]);$doc=$q->fetch();if(!$doc||$doc['status']!=='draft')throw new \DomainException('Somente rascunhos podem ser publicados.');$pdo->prepare("UPDATE legal_documents SET status='archived',updated_at=NOW() WHERE type=:type AND status='published'")->execute(['type'=>$doc['type']]);$pdo->prepare("UPDATE legal_documents SET status='published',published_at=NOW(),updated_at=NOW() WHERE id=:id")->execute(['id'=>$doc['id']]);$pdo->commit();Audit::log('MASTER_LEGAL_DOCUMENT_PUBLISHED','legal_documents',(int)$id,null,['type'=>$doc['type'],'version'=>$doc['version']]);}catch(\DomainException $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(422,$e->getMessage());}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}header('Location: /master/documentos-legais');exit;
    }
}
