<?php
namespace App\Services;use App\Core\Database;
final class PublicTranslationService
{
 public static function apply(array $tenant,string $locale):array{if($locale==='pt_BR'||empty($tenant['id']))return$tenant;$q=Database::connection()->prepare('SELECT content_key,content_value FROM public_content_translations WHERE tenant_id=:t AND locale=:l AND content_value IS NOT NULL');$q->execute(['t'=>$tenant['id'],'l'=>$locale]);$map=['headline'=>'public_headline','subheadline'=>'public_subheadline','cta'=>'public_cta_label','announcement'=>'public_announcement'];foreach($q->fetchAll() as $row)if(isset($map[$row['content_key']])&&trim((string)$row['content_value'])!=='')$tenant[$map[$row['content_key']]]=$row['content_value'];return$tenant;}
}
