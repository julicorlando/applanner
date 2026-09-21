<?php
namespace App\Services;
final class ErrorLogService
{
    public static function recent(int $limit=100,?string $search=null):array
    {
        $file=__DIR__.'/../../storage/logs/app.log';if(!is_file($file))return [];$raw=(string)file_get_contents($file);$blocks=preg_split('/\n\n(?=\[\d{4}-\d{2}-\d{2}T)/',$raw)?:[];$out=[];
        foreach(array_reverse($blocks) as $block){if($search && stripos($block,$search)===false)continue;if(preg_match('/^\[([^\]]+)\] \[([^\]]+)\] (.*?) in (.*?):(\d+)/s',$block,$m))$out[]=['at'=>$m[1],'id'=>$m[2],'message'=>trim(strtok($m[3],"\n")),'file'=>$m[4],'line'=>(int)$m[5],'raw'=>$block];if(count($out)>=$limit)break;}return $out;
    }
}
