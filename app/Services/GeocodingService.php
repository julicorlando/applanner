<?php
namespace App\Services;

final class GeocodingService
{
    public function byAddress(array $parts):?array
    {
        if(!function_exists('curl_init'))return null;$address=implode(', ',array_filter([trim((string)($parts['street']??'')),trim((string)($parts['number']??'')),trim((string)($parts['district']??'')),trim((string)($parts['city']??'')),trim((string)($parts['state']??'')),preg_replace('/\D/','',(string)($parts['postal_code']??'')),'Brasil']));if(mb_strlen($address)<10)return null;$url='https://nominatim.openstreetmap.org/search?'.http_build_query(['q'=>$address,'format'=>'jsonv2','limit'=>1,'countrycodes'=>'br','addressdetails'=>1]);$ch=curl_init($url);curl_setopt_array($ch,[CURLOPT_RETURNTRANSFER=>true,CURLOPT_FOLLOWLOCATION=>false,CURLOPT_CONNECTTIMEOUT=>4,CURLOPT_TIMEOUT=>8,CURLOPT_HTTPHEADER=>['Accept: application/json','User-Agent: ApPlanner/1.0 (https://applanner.com.br; contato@applanner.com.br)']]);$raw=curl_exec($ch);$status=(int)curl_getinfo($ch,CURLINFO_RESPONSE_CODE);curl_close($ch);if($raw===false||$status!==200)return null;try{$data=json_decode($raw,true,512,JSON_THROW_ON_ERROR);}catch(\Throwable){return null;}$first=$data[0]??null;if(!is_array($first))return null;$lat=filter_var($first['lat']??null,FILTER_VALIDATE_FLOAT);$lng=filter_var($first['lon']??null,FILTER_VALIDATE_FLOAT);if($lat===false||$lng===false||$lat<-90||$lat>90||$lng<-180||$lng>180)return null;return ['latitude'=>(float)$lat,'longitude'=>(float)$lng,'display_name'=>(string)($first['display_name']??$address),'source'=>'nominatim'];
    }

    public function byPostalCode(string $postalCode):?array
    {
        $cep=preg_replace('/\D/','',$postalCode);if(strlen($cep)!==8||!function_exists('curl_init'))return null;
        $ch=curl_init('https://brasilapi.com.br/api/cep/v2/'.$cep);curl_setopt_array($ch,[CURLOPT_RETURNTRANSFER=>true,CURLOPT_FOLLOWLOCATION=>false,CURLOPT_CONNECTTIMEOUT=>3,CURLOPT_TIMEOUT=>6,CURLOPT_HTTPHEADER=>['Accept: application/json','User-Agent: ApPlanner/1.0']]);$raw=curl_exec($ch);$status=(int)curl_getinfo($ch,CURLINFO_RESPONSE_CODE);curl_close($ch);if($raw===false||$status!==200)return null;
        try{$data=json_decode($raw,true,512,JSON_THROW_ON_ERROR);}catch(\Throwable){return null;}$coordinates=$data['location']['coordinates']??[];$lat=filter_var($coordinates['latitude']??null,FILTER_VALIDATE_FLOAT);$lng=filter_var($coordinates['longitude']??null,FILTER_VALIDATE_FLOAT);if($lat===false||$lng===false||$lat<-90||$lat>90||$lng<-180||$lng>180)return null;
        return ['latitude'=>(float)$lat,'longitude'=>(float)$lng,'postal_code'=>$cep,'city'=>(string)($data['city']??''),'state'=>(string)($data['state']??''),'district'=>(string)($data['neighborhood']??''),'street'=>(string)($data['street']??'')];
    }
}
