<?php
namespace App\Controllers;

use App\Core\{Auth,Audit,CSRF,Database,HttpException,View};
use App\Services\BackupService;

final class BackupController
{
    public function index():void
    {
        Auth::requireRole('master');$rows=Database::connection()->query('SELECT * FROM backups ORDER BY id DESC LIMIT 100')->fetchAll();
        View::render('master/backups',['title'=>'Backups do sistema','backups'=>$rows,'success'=>$_SESSION['backup_success']??null,'error'=>$_SESSION['backup_error']??null]);unset($_SESSION['backup_success'],$_SESSION['backup_error']);
    }

    public function create():void
    {
        Auth::requireRole('master');CSRF::enforce();@set_time_limit(300);
        try{$result=(new BackupService())->create();Audit::log('MASTER_BACKUP_CREATED','backups',(int)$result['id'],null,['file'=>$result['name'],'size'=>$result['size']]);$_SESSION['backup_success']='Backup criado com sucesso: '.$result['name'];}
        catch(\Throwable $e){$_SESSION['backup_error']='Não foi possível concluir o backup. Consulte a Central de Erros e as permissões da pasta storage.';}
        header('Location: /master/backups');exit;
    }

    public function download(string $id):void
    {
        Auth::requireRole('master');$pdo=Database::connection();$q=$pdo->prepare("SELECT id,path,status FROM backups WHERE id=:id AND status='completed'");$q->execute(['id'=>(int)$id]);$row=$q->fetch();if(!$row)HttpException::abort(404,'Backup não encontrado.');
        $base=realpath((new BackupService())->directory());$file=realpath((string)$row['path']);if(!$base||!$file||!str_starts_with($file,$base.DIRECTORY_SEPARATOR)||!is_file($file))HttpException::abort(404,'Arquivo de backup indisponível.');
        Audit::log('MASTER_BACKUP_DOWNLOADED','backups',(int)$row['id']);header('Content-Type: application/sql');header('Content-Disposition: attachment; filename="'.basename($file).'"');header('Content-Length: '.filesize($file));header('X-Content-Type-Options: nosniff');readfile($file);exit;
    }

    public function restoreTest(string $id):void
    {
        Auth::requireRole('master');CSRF::enforce();@set_time_limit(600);$pdo=Database::connection();$q=$pdo->prepare("SELECT * FROM backups WHERE id=:id AND status='completed'");$q->execute(['id'=>(int)$id]);$backup=$q->fetch();if(!$backup)HttpException::abort(404,'Backup não encontrado.');try{$result=(new BackupService())->testRestore($backup,(int)Auth::user()['id']);Audit::log('MASTER_BACKUP_RESTORE_TESTED','backups',(int)$id,null,$result);$_SESSION['backup_success']='Restauração isolada concluída: '.$result['tables'].' tabela(s) validadas.';}catch(\Throwable $e){error_log('[ApPlanner Restore Test] '.mb_substr($e->getMessage(),0,500));$_SESSION['backup_error']='Teste de restauração falhou: '.mb_substr($e->getMessage(),0,220);}header('Location: /master/backups');exit;
    }
}
