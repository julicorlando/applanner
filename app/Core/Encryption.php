<?php
namespace App\Core;

final class Encryption
{
    public static function encrypt(array $value): string
    {
        $key=self::key(); $iv=random_bytes(12); $tag='';
        $cipher=openssl_encrypt(json_encode($value,JSON_THROW_ON_ERROR),'aes-256-gcm',$key,OPENSSL_RAW_DATA,$iv,$tag);
        if($cipher===false) throw new \RuntimeException('Falha ao proteger dados.');
        return base64_encode($iv.$tag.$cipher);
    }
    public static function decrypt(string $value): array
    {
        $raw=base64_decode($value,true); if($raw===false||strlen($raw)<29) throw new \RuntimeException('Payload inválido.');
        $plain=openssl_decrypt(substr($raw,28),'aes-256-gcm',self::key(),OPENSSL_RAW_DATA,substr($raw,0,12),substr($raw,12,16));
        if($plain===false) throw new \RuntimeException('Payload adulterado.');
        return json_decode($plain,true,512,JSON_THROW_ON_ERROR);
    }
    private static function key(): string
    {
        $app=require __DIR__.'/../../config/app.php'; $encoded=(string)($app['app_key']??''); $key=base64_decode($encoded,true);
        if($key===false||strlen($key)!==32) throw new \RuntimeException('APP_KEY inválida.'); return $key;
    }
}
