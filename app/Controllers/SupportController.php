<?php
namespace App\Controllers;

use App\Core\{Auth,Authorization,CSRF,Database,TenantContext,View,Audit,HttpException};
use App\Services\NotificationService;

final class SupportController
{
    public function index():void
    {
        Auth::requireLogin();$pdo=Database::connection();$platform=Auth::isPlatformStaff();
        if($platform){Authorization::require('master.support.manage');if((Auth::user()['role']??'')==='commercial'){$q=$pdo->prepare('SELECT st.*,t.name tenant_name,u.name user_name,a.name assigned_name FROM support_tickets st JOIN tenants t ON t.id=st.tenant_id JOIN users u ON u.id=st.user_id LEFT JOIN users a ON a.id=st.assigned_to WHERE st.assigned_to=:assignee ORDER BY FIELD(st.status,\'open\',\'in_progress\',\'waiting_user\',\'resolved\',\'closed\'),st.updated_at DESC');$q->execute(['assignee'=>Auth::user()['id']]);$tickets=$q->fetchAll();}else{$tickets=$pdo->query('SELECT st.*,t.name tenant_name,u.name user_name,a.name assigned_name FROM support_tickets st JOIN tenants t ON t.id=st.tenant_id JOIN users u ON u.id=st.user_id LEFT JOIN users a ON a.id=st.assigned_to ORDER BY FIELD(st.status,\'open\',\'in_progress\',\'waiting_user\',\'resolved\',\'closed\'),st.updated_at DESC')->fetchAll();}}
        else{$q=$pdo->prepare('SELECT st.*,NULL tenant_name FROM support_tickets st WHERE st.tenant_id=:t ORDER BY st.updated_at DESC');$q->execute(['t'=>TenantContext::id()]);$tickets=$q->fetchAll();}
        View::render('support/index',['title'=>$platform?'Suporte aos clientes':'Suporte','tickets'=>$tickets,'platform'=>$platform]);
    }

    public function store():void
    {
        Authorization::require('support.create');CSRF::enforce();$subject=trim((string)($_POST['subject']??''));$description=trim((string)($_POST['description']??''));if(strlen($subject)<3||strlen($description)<10){http_response_code(422);exit('Descreva melhor o chamado.');}
        $category=(string)($_POST['category']??'other');$priority=(string)($_POST['priority']??'normal');
        if(!in_array($category,['technical','question','billing','integration','suggestion','other'],true))$category='other';
        if(!in_array($priority,['low','normal','high','urgent'],true))$priority='normal';
        $protocol='SUP-'.date('ymd').'-'.strtoupper(substr(bin2hex(random_bytes(4)),0,6));$allow=isset($_POST['remote_access'])?1:0;
        Database::connection()->prepare("INSERT INTO support_tickets(protocol,tenant_id,user_id,category,subject,description,source_url,browser_context,app_version,error_id,priority,status,remote_access_allowed,remote_access_allowed_at,created_at,updated_at)VALUES(:p,:t,:u,:c,:s,:d,:source,:browser,:version,:error,:priority,'open',:allow,IF(:allow2=1,NOW(),NULL),NOW(),NOW())")
            ->execute(['p'=>$protocol,'t'=>TenantContext::id(),'u'=>Auth::user()['id'],'c'=>$category,'s'=>$subject,'d'=>$description,'source'=>substr((string)($_POST['source_url']??''),0,500)?:null,'browser'=>substr((string)($_POST['browser_context']??($_SERVER['HTTP_USER_AGENT']??'')),0,500)?:null,'version'=>substr((string)($_POST['app_version']??'4.0.0 RC'),0,40),'error'=>preg_match('/^ERR-\d{8}-[A-F0-9]{6}$/',(string)($_POST['error_id']??''))?(string)$_POST['error_id']:null,'priority'=>$priority,'allow'=>$allow,'allow2'=>$allow]);
        $id=(int)Database::connection()->lastInsertId();Audit::log('SUPPORT_TICKET_CREATED','support_tickets',$id,null,['remote_access_allowed'=>(bool)$allow]);
        NotificationService::platformStaff('support.new','Novo chamado de suporte',$protocol.' — '.$subject,'/support/'.$id,$priority==='urgent'?'danger':($priority==='high'?'warning':'info'));
        header('Location: /support/'.$id);exit;
    }

    public function show(string $id):void
    {
        Auth::requireLogin();$ticket=$this->ticket((int)$id);$pdo=Database::connection();
        $q=$pdo->prepare('SELECT sm.*,u.name user_name,u.tenant_id user_tenant FROM support_messages sm JOIN users u ON u.id=sm.user_id WHERE sm.ticket_id=:id ORDER BY sm.id');$q->execute(['id'=>$ticket['id']]);
        $access=$pdo->prepare('SELECT sas.*,u.name master_name FROM support_access_sessions sas LEFT JOIN users u ON u.id=sas.master_user_id WHERE sas.ticket_id=:id ORDER BY sas.id DESC LIMIT 20');$access->execute(['id'=>$ticket['id']]);
        $assignees=[];if((Auth::user()['role']??'')==='master')$assignees=$pdo->query("SELECT u.id,u.name,r.slug role_slug FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id LEFT JOIN commercial_profiles cp ON cp.user_id=u.id WHERE u.tenant_id IS NULL AND u.status='active' AND (r.slug='support' OR (r.slug='commercial' AND cp.active=1 AND cp.support_enabled=1)) ORDER BY u.name")->fetchAll();View::render('support/show-v2',['title'=>'Chamado '.$ticket['protocol'],'ticket'=>$ticket,'messages'=>$q->fetchAll(),'accessSessions'=>$access->fetchAll(),'platform'=>Auth::isPlatformStaff(),'assignees'=>$assignees]);
    }

    public function message(string $id):void
    {
        Auth::requireLogin();CSRF::enforce();$ticket=$this->ticket((int)$id);$message=trim((string)($_POST['message']??''));if(strlen($message)<2){http_response_code(422);exit('Digite uma mensagem.');}
        $attachment=$this->storeAttachment($ticket);
        $pdo=Database::connection();$pdo->prepare('INSERT INTO support_messages(ticket_id,user_id,message,attachment_path,created_at)VALUES(:t,:u,:m,:a,NOW())')->execute(['t'=>$ticket['id'],'u'=>Auth::user()['id'],'m'=>$message,'a'=>$attachment]);
        $newStatus=Auth::isPlatformStaff()?'waiting_user':'open';$pdo->prepare('UPDATE support_tickets SET status=:s,updated_at=NOW() WHERE id=:id')->execute(['s'=>$newStatus,'id'=>$ticket['id']]);Audit::log('SUPPORT_MESSAGE_CREATED','support_tickets',(int)$ticket['id']);
        if(Auth::isPlatformStaff())NotificationService::user((int)$ticket['user_id'],(int)$ticket['tenant_id'],'support.reply','Nova resposta do suporte','O chamado '.$ticket['protocol'].' recebeu uma resposta.','/support/'.$ticket['id'],'info');
        else NotificationService::platformStaff('support.reply','Cliente respondeu ao chamado',$ticket['protocol'].' — '.$ticket['subject'],'/support/'.$ticket['id'],'info');
        header('Location: /support/'.$ticket['id']);exit;
    }

    public function remoteAccess(string $id):void
    {
        Auth::requireLogin();if(Auth::isPlatformStaff())HttpException::abort(403,'A autorização deve ser concedida pelo cliente.');CSRF::enforce();$ticket=$this->ticket((int)$id);$allow=isset($_POST['allow'])?1:0;
        Database::connection()->prepare('UPDATE support_tickets SET remote_access_allowed=:a,remote_access_allowed_at=IF(:a2=1,NOW(),remote_access_allowed_at),remote_access_revoked_at=IF(:a3=0,NOW(),NULL),updated_at=NOW() WHERE id=:id AND tenant_id=:t')
            ->execute(['a'=>$allow,'a2'=>$allow,'a3'=>$allow,'id'=>$ticket['id'],'t'=>TenantContext::id()]);Audit::log($allow?'SUPPORT_REMOTE_ACCESS_GRANTED':'SUPPORT_REMOTE_ACCESS_REVOKED','support_tickets',(int)$ticket['id']);
        NotificationService::platformStaff($allow?'support.access_granted':'support.access_revoked',$allow?'Acesso remoto autorizado':'Acesso remoto revogado',$ticket['protocol'].' — '.$ticket['subject'],'/support/'.$ticket['id'],$allow?'success':'warning');
        header('Location: /support/'.$ticket['id']);exit;
    }

    public function startAccess(string $id):void
    {
        Auth::requireLogin();Authorization::require('master.support.impersonate');CSRF::enforce();$ticket=$this->ticket((int)$id);if(!$ticket['remote_access_allowed']||in_array($ticket['status'],['resolved','closed'],true))HttpException::abort(403,'O cliente não autorizou acesso assistido para este chamado ativo.');
        $pdo=Database::connection();$q=$pdo->prepare("SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id WHERE u.tenant_id=:t AND u.status='active' AND r.slug='owner' ORDER BY u.id LIMIT 1");$q->execute(['t'=>$ticket['tenant_id']]);$target=(int)$q->fetchColumn();if(!$target)HttpException::abort(409,'Nenhum proprietário ativo disponível para o acesso assistido.');
        $pdo->prepare('INSERT INTO support_access_sessions(ticket_id,tenant_id,master_user_id,impersonated_user_id,started_at,ip_address,actions_json)VALUES(:ticket,:tenant,:master,:target,NOW(),:ip,JSON_ARRAY())')->execute(['ticket'=>$ticket['id'],'tenant'=>$ticket['tenant_id'],'master'=>Auth::user()['id'],'target'=>$target,'ip'=>$_SERVER['REMOTE_ADDR']??null]);$sessionId=(int)$pdo->lastInsertId();
        Audit::log('SUPPORT_ACCESS_STARTED','support_tickets',(int)$ticket['id'],null,['tenant_id'=>(int)$ticket['tenant_id'],'access_session_id'=>$sessionId]);Auth::beginSupportAccess($target,(int)$ticket['id'],$sessionId);header('Location: /dashboard');exit;
    }

    public function endAccess():void
    {
        Auth::requireLogin();CSRF::enforce();if(!Auth::isSupportImpersonating())HttpException::abort(409,'Nenhum acesso assistido ativo.');$meta=Auth::supportMeta();$pdo=Database::connection();$accessId=(int)($meta['access_session_id']??0);if($accessId)$pdo->prepare('UPDATE support_access_sessions SET ended_at=NOW() WHERE id=:id AND ended_at IS NULL')->execute(['id'=>$accessId]);Auth::endSupportAccess();Audit::log('SUPPORT_ACCESS_ENDED','support_tickets',(int)($meta['ticket_id']??0),null,['access_session_id'=>$accessId]);header('Location: /master/support');exit;
    }

    public function status(string $id):void
    {
        Authorization::require('master.support.manage');CSRF::enforce();$ticket=$this->ticket((int)$id);$status=(string)($_POST['status']??'');if(!in_array($status,['open','in_progress','waiting_user','resolved','closed'],true)){http_response_code(422);exit('Status inválido.');}Database::connection()->prepare('UPDATE support_tickets SET status=:s,updated_at=NOW() WHERE id=:id')->execute(['s'=>$status,'id'=>$ticket['id']]);Audit::log('SUPPORT_STATUS_CHANGED','support_tickets',(int)$ticket['id'],null,['status'=>$status]);
        NotificationService::user((int)$ticket['user_id'],(int)$ticket['tenant_id'],'support.status','Status do chamado atualizado',$ticket['protocol'].' agora está como '.$status.'.','/support/'.$ticket['id'],$status==='resolved'?'success':'info');
        header('Location: /support/'.$ticket['id']);exit;
    }

    public function assign(string $id):void
    {
        Auth::requireRole('master');CSRF::enforce();$ticket=$this->ticket((int)$id);$assignee=(int)($_POST['assigned_to']??0);$pdo=Database::connection();if($assignee){$q=$pdo->prepare("SELECT 1 FROM users u JOIN user_roles ur ON ur.user_id=u.id JOIN roles r ON r.id=ur.role_id LEFT JOIN commercial_profiles cp ON cp.user_id=u.id WHERE u.id=:u AND u.tenant_id IS NULL AND u.status='active' AND (r.slug='support' OR (r.slug='commercial' AND cp.active=1 AND cp.support_enabled=1))");$q->execute(['u'=>$assignee]);if(!$q->fetchColumn())HttpException::abort(422,'Responsável não possui permissão de suporte.');}$pdo->prepare("UPDATE support_tickets SET assigned_to=:u,status=IF(:u2 IS NULL,'open','in_progress'),updated_at=NOW() WHERE id=:id")->execute(['u'=>$assignee?:null,'u2'=>$assignee?:null,'id'=>$ticket['id']]);if($assignee)NotificationService::user($assignee,null,'support.assigned','Chamado atribuído a você',$ticket['protocol'].' — '.$ticket['subject'],'/support/'.$ticket['id'],'warning');Audit::log('SUPPORT_TICKET_ASSIGNED','support_tickets',(int)$ticket['id'],null,['assigned_to'=>$assignee?:null]);header('Location: /support/'.$ticket['id']);exit;
    }

    public function attachment(string $id):void
    {
        Auth::requireLogin();$pdo=Database::connection();$q=$pdo->prepare('SELECT sm.attachment_path,sm.ticket_id,st.tenant_id FROM support_messages sm JOIN support_tickets st ON st.id=sm.ticket_id WHERE sm.id=:id');$q->execute(['id'=>(int)$id]);$row=$q->fetch();if(!$row||empty($row['attachment_path']))HttpException::abort(404,'Anexo não encontrado.');
        if(!Auth::isPlatformStaff()&&(int)$row['tenant_id']!==TenantContext::id())HttpException::abort(404,'Anexo não encontrado.');
        if(Auth::isPlatformStaff())Authorization::require('master.support.manage');
        $base=realpath(dirname(__DIR__,2).'/storage/private/support');$file=realpath(dirname(__DIR__,2).'/storage/private/support/'.ltrim((string)$row['attachment_path'],'/'));
        if(!$base||!$file||!str_starts_with($file,$base.DIRECTORY_SEPARATOR)||!is_file($file))HttpException::abort(404,'Anexo não encontrado.');
        $finfo=new \finfo(FILEINFO_MIME_TYPE);$mime=$finfo->file($file)?:'application/octet-stream';header('Content-Type: '.$mime);header('Content-Length: '.filesize($file));header('Content-Disposition: attachment; filename="anexo-'.(int)$id.'.'.pathinfo($file,PATHINFO_EXTENSION).'"');header('Cache-Control: private, no-store');readfile($file);exit;
    }

    private function storeAttachment(array $ticket):?string
    {
        if(empty($_FILES['attachment'])||($_FILES['attachment']['error']??UPLOAD_ERR_NO_FILE)===UPLOAD_ERR_NO_FILE)return null;
        $f=$_FILES['attachment'];if(($f['error']??UPLOAD_ERR_OK)!==UPLOAD_ERR_OK)HttpException::abort(422,'Falha ao receber o anexo.');if((int)($f['size']??0)>5*1024*1024)HttpException::abort(422,'O anexo deve ter no máximo 5 MB.');
        $tmp=(string)($f['tmp_name']??'');if(!is_uploaded_file($tmp))HttpException::abort(422,'Upload inválido.');$fi=new \finfo(FILEINFO_MIME_TYPE);$mime=$fi->file($tmp)?:'';$allowed=['image/jpeg'=>'jpg','image/png'=>'png','application/pdf'=>'pdf','text/plain'=>'txt'];if(!isset($allowed[$mime]))HttpException::abort(422,'Formato de anexo não permitido.');
        $dir=dirname(__DIR__,2).'/storage/private/support/'.(int)$ticket['tenant_id'];if(!is_dir($dir)&&!mkdir($dir,0750,true)&&!is_dir($dir))throw new \RuntimeException('Não foi possível preparar o diretório privado de suporte.');$name=bin2hex(random_bytes(20)).'.'.$allowed[$mime];$dest=$dir.'/'.$name;if(!move_uploaded_file($tmp,$dest))throw new \RuntimeException('Não foi possível salvar o anexo.');@chmod($dest,0640);return (int)$ticket['tenant_id'].'/'.$name;
    }

    private function ticket(int $id):array
    {
        $pdo=Database::connection();
        if(Auth::isPlatformStaff()){if((Auth::user()['role']??'')==='commercial'){$q=$pdo->prepare('SELECT st.*,t.name tenant_name,u.name user_name FROM support_tickets st JOIN tenants t ON t.id=st.tenant_id JOIN users u ON u.id=st.user_id WHERE st.id=:id AND st.assigned_to=:assignee');$q->execute(['id'=>$id,'assignee'=>Auth::user()['id']]);}else{$q=$pdo->prepare('SELECT st.*,t.name tenant_name,u.name user_name FROM support_tickets st JOIN tenants t ON t.id=st.tenant_id JOIN users u ON u.id=st.user_id WHERE st.id=:id');$q->execute(['id'=>$id]);}}
        else{$q=$pdo->prepare('SELECT st.*,NULL tenant_name FROM support_tickets st WHERE st.id=:id AND st.tenant_id=:t');$q->execute(['id'=>$id,'t'=>TenantContext::id()]);}
        $ticket=$q->fetch();if(!$ticket)HttpException::abort(404,'Chamado não encontrado.');return $ticket;
    }
}
