<?php
namespace App\Controllers;
use App\Core\{Authorization,CSRF,Database,Auth,View,HttpException};
final class NotificationController
{
    private function access():void{Auth::requireLogin();if(!Auth::isPlatformStaff()&&!Authorization::allows('notifications.view'))HttpException::abort(403,'Você não possui permissão para visualizar notificações.');}
    public function index():void{$this->access();$q=Database::connection()->prepare('SELECT * FROM user_notifications WHERE user_id=:u ORDER BY read_at IS NULL DESC,created_at DESC LIMIT 300');$q->execute(['u'=>Auth::user()['id']]);View::render('notifications/index',['title'=>'Notificações','items'=>$q->fetchAll()]);}
    public function read(string $id):void{$this->access();CSRF::enforce();Database::connection()->prepare('UPDATE user_notifications SET read_at=COALESCE(read_at,NOW()) WHERE id=:id AND user_id=:u')->execute(['id'=>(int)$id,'u'=>Auth::user()['id']]);header('Location: /notifications');exit;}
    public function readAll():void{$this->access();CSRF::enforce();Database::connection()->prepare('UPDATE user_notifications SET read_at=COALESCE(read_at,NOW()) WHERE user_id=:u')->execute(['u'=>Auth::user()['id']]);header('Location: /notifications');exit;}
}
