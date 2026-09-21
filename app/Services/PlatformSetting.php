<?php
namespace App\Services;

use App\Core\{Database,Encryption};

final class PlatformSetting
{
    public static function get(string $key, ?string $default=null): ?string
    {
        $q=Database::connection()->prepare('SELECT setting_value FROM settings WHERE tenant_id IS NULL AND setting_key=:k ORDER BY id DESC LIMIT 1');
        $q->execute(['k'=>$key]);$v=$q->fetchColumn();return $v===false?$default:(string)$v;
    }

    public static function getRow(string $key): ?array
    {
        $q=Database::connection()->prepare('SELECT id,setting_key,setting_value,is_secret,updated_at FROM settings WHERE tenant_id IS NULL AND setting_key=:k ORDER BY id DESC LIMIT 1');$q->execute(['k'=>$key]);$row=$q->fetch();return $row?:null;
    }

    public static function json(string $key,array $default=[]):array
    {
        $v=self::get($key);if($v===null)return $default;$decoded=json_decode($v,true);return is_array($decoded)?$decoded:$default;
    }

    public static function secret(string $key,array $default=[]):array
    {
        $v=self::get($key);if($v===null)return $default;try{$data=Encryption::decrypt($v);return is_array($data)?$data:$default;}catch(\Throwable){return $default;}
    }

    public static function set(string $key,?string $value,bool $secret=false):void
    {
        $pdo=Database::connection();$lock='platform-setting:'.hash('sha256',$key);$l=$pdo->prepare('SELECT GET_LOCK(:l,5)');$l->execute(['l'=>$lock]);if((int)$l->fetchColumn()!==1)throw new \RuntimeException('Configuração global ocupada. Tente novamente.');
        try{$pdo->beginTransaction();$q=$pdo->prepare('SELECT id FROM settings WHERE tenant_id IS NULL AND setting_key=:k ORDER BY id DESC FOR UPDATE');$q->execute(['k'=>$key]);$ids=array_map('intval',$q->fetchAll(\PDO::FETCH_COLUMN));if($ids){$keep=array_shift($ids);$pdo->prepare('UPDATE settings SET setting_value=:v,is_secret=:s,updated_at=NOW() WHERE id=:id')->execute(['v'=>$value,'s'=>$secret?1:0,'id'=>$keep]);if($ids){$marks=implode(',',array_fill(0,count($ids),'?'));$pdo->prepare("DELETE FROM settings WHERE id IN ($marks)")->execute($ids);}}else{$pdo->prepare('INSERT INTO settings(tenant_id,setting_key,setting_value,is_secret,updated_at)VALUES(NULL,:k,:v,:s,NOW())')->execute(['k'=>$key,'v'=>$value,'s'=>$secret?1:0]);}$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}finally{$r=$pdo->prepare('SELECT RELEASE_LOCK(:l)');$r->execute(['l'=>$lock]);}
    }

    public static function setSecret(string $key,array $value):void{self::set($key,Encryption::encrypt($value),true);}
}
