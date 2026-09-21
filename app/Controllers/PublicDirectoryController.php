<?php
namespace App\Controllers;

use App\Core\{Database,View};
use App\Services\{AvailabilityService,GeocodingService,SportsAvailabilityService,ArenaTenantService};

final class PublicDirectoryController
{
    public function companyLocation(string $slug):void
    {
        header('Content-Type: application/json; charset=UTF-8');$q=Database::connection()->prepare("SELECT t.name,u.address,u.address_number,u.district,u.city,u.state,u.latitude,u.longitude FROM tenants t JOIN units u ON u.id=(SELECT u2.id FROM units u2 WHERE u2.tenant_id=t.id AND u2.active=1 ORDER BY u2.is_primary DESC,u2.id LIMIT 1) WHERE (t.public_slug=:slug OR t.public_short_code=:code) AND t.status IN('trial','active') AND t.public_enabled=1 AND t.deleted_at IS NULL LIMIT 1");$q->execute(['slug'=>$slug,'code'=>$slug]);$row=$q->fetch();if(!$row||$row['latitude']===null||$row['longitude']===null){http_response_code(404);echo json_encode(['ok'=>false]);return;}echo json_encode(['ok'=>true,'name'=>$row['name'],'latitude'=>(float)$row['latitude'],'longitude'=>(float)$row['longitude'],'address'=>implode(', ',array_filter([$row['address'],$row['address_number'],$row['district'],$row['city'],$row['state']]))],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);
    }

    public function index():void
    {
        $lat=$this->coordinate($_GET['lat']??null,-90,90);$lng=$this->coordinate($_GET['lng']??null,-180,180);$cep=preg_replace('/\D/','',(string)($_GET['cep']??''));$locationMessage='';
        if(($lat===null||$lng===null)&&strlen($cep)===8){$geo=(new GeocodingService())->byPostalCode($cep);if($geo){$lat=$geo['latitude'];$lng=$geo['longitude'];$locationMessage='Resultados próximos ao CEP '.substr($cep,0,5).'-'.substr($cep,5);}else{$locationMessage='Não foi possível localizar esse CEP. Mostrando estabelecimentos cadastrados.';}}
        $pdo=Database::connection();$sql="SELECT t.id,t.name,t.public_slug,t.public_short_code,t.category,t.description,t.logo_path,t.primary_color,u.id unit_id,u.name unit_name,u.address,u.address_number,u.district,u.city,u.state,u.postal_code,u.latitude,u.longitude,u.whatsapp,u.phone,EXISTS(SELECT 1 FROM tenant_modules tm JOIN modules m ON m.id=tm.module_id WHERE tm.tenant_id=t.id AND tm.enabled=1 AND m.slug='waitlist' AND m.active=1) waitlist_enabled,EXISTS(SELECT 1 FROM modules m JOIN subscriptions s3 ON s3.id=(SELECT MAX(s4.id) FROM subscriptions s4 WHERE s4.tenant_id=t.id) LEFT JOIN plan_modules pm3 ON pm3.plan_id=s3.plan_id AND pm3.module_id=m.id LEFT JOIN tenant_modules tm3 ON tm3.tenant_id=t.id AND tm3.module_id=m.id WHERE m.slug='sports_courts' AND m.active=1 AND COALESCE(tm3.enabled,pm3.enabled,0)=1) sports_enabled FROM tenants t JOIN units u ON u.id=(SELECT u2.id FROM units u2 WHERE u2.tenant_id=t.id AND u2.active=1 ORDER BY u2.is_primary DESC,u2.id LIMIT 1) WHERE t.status IN('trial','active') AND t.public_enabled=1 AND t.public_booking_enabled=1 AND t.deleted_at IS NULL ORDER BY t.name LIMIT 60";$rows=$pdo->query($sql)->fetchAll();
        $geocoder=new GeocodingService();$backfilled=0;foreach($rows as &$row){if(($row['latitude']===null||$row['longitude']===null)&&strlen(preg_replace('/\D/','',(string)$row['postal_code']))===8&&$backfilled<5){$geo=$geocoder->byPostalCode((string)$row['postal_code']);if($geo){$q=$pdo->prepare('UPDATE units SET latitude=:lat,longitude=:lng,geocoded_at=NOW() WHERE id=:id');$q->execute(['lat'=>$geo['latitude'],'lng'=>$geo['longitude'],'id'=>$row['unit_id']]);$row['latitude']=$geo['latitude'];$row['longitude']=$geo['longitude'];}$backfilled++;}$row['distance_km']=$lat!==null&&$lng!==null&&$row['latitude']!==null&&$row['longitude']!==null?$this->distance($lat,$lng,(float)$row['latitude'],(float)$row['longitude']):null;}
        unset($row);if($lat!==null&&$lng!==null){usort($rows,fn($a,$b)=>($a['distance_km']??PHP_FLOAT_MAX)<=>($b['distance_km']??PHP_FLOAT_MAX));if($locationMessage==='')$locationMessage='Estabelecimentos ordenados pela distância da sua localização.';}$rows=array_slice($rows,0,24);foreach($rows as &$row){$row['is_arena']=!empty($row['sports_enabled']);$row['public_path']=ArenaTenantService::publicPath($row,(int)$row['id']);$row['next_availability']=$this->nextAvailability((int)$row['id'],(bool)$row['is_arena']);}unset($row);
        View::render('public/directory',['title'=>'Estabelecimentos perto de você','publicLayout'=>true,'establishments'=>$rows,'cep'=>$cep,'hasOrigin'=>$lat!==null&&$lng!==null,'locationMessage'=>$locationMessage]);
    }
    private function nextAvailability(int $tenantId,bool $isArena=false):?array
    {
        if($isArena)return $this->nextArenaAvailability($tenantId);
        $pdo=Database::connection();$s=$pdo->prepare('SELECT id,name FROM services WHERE tenant_id=:t AND active=1 ORDER BY duration_minutes,id LIMIT 1');$s->execute(['t'=>$tenantId]);$service=$s->fetch();if(!$service)return null;$p=$pdo->prepare('SELECT id,name FROM professionals WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 6');$p->execute(['t'=>$tenantId]);$professionals=$p->fetchAll();if(!$professionals)return null;$engine=new AvailabilityService();
        for($offset=0;$offset<15;$offset++){$day=(new \DateTimeImmutable('today'))->modify('+'.$offset.' days');foreach($professionals as $professional){$slots=$engine->slots($tenantId,(int)$service['id'],(int)$professional['id'],$day);if($slots)return ['date'=>$day->format('Y-m-d'),'date_label'=>$this->dateLabel($day,$offset),'time'=>$slots[0]['label'],'service'=>$service['name'],'professional'=>$professional['name']];}}
        return null;
    }

    private function nextArenaAvailability(int $tenantId):?array
    {
        $pdo=Database::connection();
        $q=$pdo->prepare("SELECT c.id court_id,c.name court_name,c.minimum_minutes,m.id modality_id,m.name modality_name FROM sports_courts c JOIN sports_court_modalities cm ON cm.court_id=c.id JOIN sports_modalities m ON m.id=cm.modality_id AND m.tenant_id=c.tenant_id AND m.active=1 WHERE c.tenant_id=:t AND c.active=1 ORDER BY c.sort_order,c.id,m.name LIMIT 24");
        $q->execute(['t'=>$tenantId]);$pairs=$q->fetchAll();if(!$pairs)return null;$engine=new SportsAvailabilityService();
        for($offset=0;$offset<15;$offset++){$day=(new \DateTimeImmutable('today'))->modify('+'.$offset.' days');foreach($pairs as $pair){$duration=max(5,(int)($pair['minimum_minutes']??60));$slots=$engine->slots($tenantId,(int)$pair['court_id'],(int)$pair['modality_id'],$day->format('Y-m-d'),$duration);if($slots)return ['date'=>$day->format('Y-m-d'),'date_label'=>$this->dateLabel($day,$offset),'time'=>$slots[0]['label'],'service'=>$pair['modality_name'],'professional'=>$pair['court_name'],'court'=>$pair['court_name'],'modality'=>$pair['modality_name'],'total'=>$slots[0]['total']??null];}}
        return null;
    }

    private function dateLabel(\DateTimeImmutable $day,int $offset):string{if($offset===0)return 'Hoje';if($offset===1)return 'Amanhã';$days=[1=>'segunda-feira',2=>'terça-feira',3=>'quarta-feira',4=>'quinta-feira',5=>'sexta-feira',6=>'sábado',7=>'domingo'];return ucfirst($days[(int)$day->format('N')]).', '.$day->format('d/m');}
    private function coordinate(mixed $value,float $min,float $max):?float{$v=filter_var($value,FILTER_VALIDATE_FLOAT);return $v!==false&&$v>=$min&&$v<=$max?(float)$v:null;}
    private function distance(float $lat1,float $lon1,float $lat2,float $lon2):float{$earth=6371;$dLat=deg2rad($lat2-$lat1);$dLon=deg2rad($lon2-$lon1);$a=sin($dLat/2)**2+cos(deg2rad($lat1))*cos(deg2rad($lat2))*sin($dLon/2)**2;return round($earth*2*atan2(sqrt($a),sqrt(1-$a)),1);}
}
