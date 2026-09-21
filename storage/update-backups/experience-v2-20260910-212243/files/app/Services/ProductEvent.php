<?php
namespace App\Services;use App\Core\Database;
final class ProductEvent{public static function record(string $type,?int $tenantId=null,?int $userId=null,array $metadata=[]):void{try{$s=Database::connection()->prepare('INSERT INTO product_events(tenant_id,user_id,event_type,metadata_json,created_at)VALUES(:tenant,:user,:type,:metadata,NOW())');$s->execute(['tenant'=>$tenantId,'user'=>$userId,'type'=>$type,'metadata'=>$metadata?json_encode($metadata,JSON_UNESCAPED_UNICODE):null]);}catch(\Throwable $e){}}}
