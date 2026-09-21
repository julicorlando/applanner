<?php
namespace App\Controllers;

use App\Core\{Auth,Authorization,CSRF,Database,TenantContext,View,Audit,HttpException};
use App\Services\{ModuleService,GeocodingService};

final class UnitController
{
    private const AMENITIES=['wifi'=>'Wi-Fi','parking'=>'Estacionamento','accessibility'=>'Acessibilidade','air_conditioning'=>'Ar-condicionado','waiting_room'=>'Sala de espera','coffee'=>'Café/água','child_friendly'=>'Espaço infantil','pet_friendly'=>'Aceita pets'];
    private const PAYMENTS=['pix'=>'Pix','cash'=>'Dinheiro','credit_card'=>'Cartão de crédito','debit_card'=>'Cartão de débito','bank_transfer'=>'Transferência','payment_link'=>'Link de pagamento'];

    public function index():void
    {
        Authorization::require('units.view');$t=TenantContext::id();$q=Database::connection()->prepare('SELECT u.*,(SELECT COUNT(*) FROM professionals p WHERE p.tenant_id=u.tenant_id AND p.unit_id=u.id AND p.active=1) professionals_count FROM units u WHERE u.tenant_id=:t ORDER BY u.active DESC,u.is_primary DESC,u.name');$q->execute(['t'=>$t]);
        View::render('units/index',['title'=>'Unidades','units'=>$q->fetchAll(),'limit'=>ModuleService::limit('units',$t,1),'canMultiunit'=>ModuleService::has('multiunit',$t)]);
    }

    public function store():void
    {
        ModuleService::require('multiunit');Authorization::require('units.manage');CSRF::enforce();$t=TenantContext::id();$name=trim((string)($_POST['name']??''));if(mb_strlen($name)<2)HttpException::abort(422,'Nome da unidade inválido.');$pdo=Database::connection();$limit=ModuleService::limit('units',$t,null);if($limit!==null){$q=$pdo->prepare('SELECT COUNT(*) FROM units WHERE tenant_id=:t AND active=1');$q->execute(['t'=>$t]);if((int)$q->fetchColumn()>=$limit)HttpException::abort(422,'Seu plano permite até '.$limit.' unidade(s).');}$q=$pdo->prepare('SELECT COUNT(*) FROM units WHERE tenant_id=:t');$q->execute(['t'=>$t]);$primary=(int)$q->fetchColumn()===0?1:0;$pdo->prepare('INSERT INTO units(tenant_id,name,address,phone,active,is_primary,created_at,updated_at)VALUES(:t,:n,:a,:p,1,:primary,NOW(),NOW())')->execute(['t'=>$t,'n'=>$name,'a'=>trim((string)($_POST['address']??''))?:null,'p'=>trim((string)($_POST['phone']??''))?:null,'primary'=>$primary]);$id=(int)$pdo->lastInsertId();Audit::log('UNIT_CREATED','units',$id);header('Location: /units/'.$id.'/edit');exit;
    }

    public function edit(string $id):void{ModuleService::require('multiunit');Authorization::require('units.manage');$this->render((int)$id,false);}
    public function lookupPostalCode(string $cep):void
    {
        Auth::requireLogin();header('Content-Type: application/json; charset=UTF-8');$data=(new GeocodingService())->byPostalCode($cep);if(!$data){http_response_code(404);echo json_encode(['ok'=>false,'message'=>'CEP não encontrado.'],JSON_UNESCAPED_UNICODE);return;}echo json_encode(['ok'=>true,'address'=>['postal_code'=>substr($data['postal_code'],0,5).'-'.substr($data['postal_code'],5),'street'=>$data['street'],'district'=>$data['district'],'city'=>$data['city'],'state'=>$data['state']]],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);
    }
    public function primaryEdit():void{Authorization::require('units.manage');$this->render($this->primaryId(),true);}
    public function update(string $id):void{ModuleService::require('multiunit');Authorization::require('units.manage');$this->save((int)$id,false);}
    public function primaryUpdate():void{Authorization::require('units.manage');$this->save($this->primaryId(),true);}

    private function primaryId():int
    {
        $t=TenantContext::id();$pdo=Database::connection();$q=$pdo->prepare('SELECT id FROM units WHERE tenant_id=:t AND active=1 ORDER BY is_primary DESC,id LIMIT 1');$q->execute(['t'=>$t]);$id=(int)$q->fetchColumn();if($id)return $id;$pdo->prepare("INSERT INTO units(tenant_id,name,active,is_primary,created_at,updated_at) SELECT id,name,1,1,NOW(),NOW() FROM tenants WHERE id=:t")->execute(['t'=>$t]);return (int)$pdo->lastInsertId();
    }

    private function render(int $id,bool $settings):void
    {
        $q=Database::connection()->prepare('SELECT * FROM units WHERE id=:id AND tenant_id=:t');$q->execute(['id'=>$id,'t'=>TenantContext::id()]);$unit=$q->fetch();if(!$unit)HttpException::abort(404,'Unidade não encontrada.');View::render('units/form',['title'=>$settings?'Dados públicos da unidade':'Editar unidade','unit'=>$unit,'settingsMode'=>$settings,'amenityOptions'=>self::AMENITIES,'paymentOptions'=>self::PAYMENTS]);
    }

    private function save(int $id,bool $settings):void
    {
        CSRF::enforce();$t=TenantContext::id();$pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM units WHERE id=:id AND tenant_id=:t');$q->execute(['id'=>$id,'t'=>$t]);$old=$q->fetch();if(!$old)HttpException::abort(404,'Unidade não encontrada.');$name=trim((string)($_POST['name']??''));if(mb_strlen($name)<2)HttpException::abort(422,'Nome inválido.');$email=mb_strtolower(trim((string)($_POST['email']??'')));if($email!==''&&!filter_var($email,FILTER_VALIDATE_EMAIL))HttpException::abort(422,'E-mail inválido.');$state=mb_strtoupper(trim((string)($_POST['state']??'')));if($state!==''&&!preg_match('/^[A-Z]{2}$/',$state))HttpException::abort(422,'UF inválida.');$urls=[];foreach(['facebook','website','map_url'] as $key){$value=trim((string)($_POST[$key]??''));if($value!==''&&!filter_var($value,FILTER_VALIDATE_URL))HttpException::abort(422,'Informe uma URL completa e válida.');$urls[$key]=$value?:null;}$amenities=array_values(array_intersect(array_keys(self::AMENITIES),(array)($_POST['amenities']??[])));$payments=array_values(array_intersect(array_keys(self::PAYMENTS),(array)($_POST['payment_methods']??[])));$primary=$settings?1:(isset($_POST['is_primary'])?1:(int)$old['is_primary']);$active=$settings?1:(isset($_POST['active'])?1:0);
        $postal=trim((string)($_POST['postal_code']??''))?:null;$addressParts=['street'=>trim((string)($_POST['address']??'')),'number'=>trim((string)($_POST['address_number']??'')),'district'=>trim((string)($_POST['district']??'')),'city'=>trim((string)($_POST['city']??'')),'state'=>$state,'postal_code'=>$postal];$oldSignature=implode('|',[$old['address']??'',$old['address_number']??'',$old['district']??'',$old['city']??'',$old['state']??'',preg_replace('/\D/','',(string)($old['postal_code']??''))]);$newSignature=implode('|',[$addressParts['street'],$addressParts['number'],$addressParts['district'],$addressParts['city'],$addressParts['state'],preg_replace('/\D/','',(string)$postal)]);$changed=$oldSignature!==$newSignature;$geocoder=new GeocodingService();$geo=($changed||empty($old['latitude'])||empty($old['longitude']))?$geocoder->byAddress($addressParts):null;if(!$geo&&($changed||empty($old['latitude'])||empty($old['longitude']))&&$postal)$geo=$geocoder->byPostalCode($postal);$latitude=$geo['latitude']??(!$changed?$old['latitude']??null:null);$longitude=$geo['longitude']??(!$changed?$old['longitude']??null:null);
        $data=['n'=>$name,'a'=>trim((string)($_POST['address']??''))?:null,'number'=>trim((string)($_POST['address_number']??''))?:null,'complement'=>trim((string)($_POST['address_complement']??''))?:null,'district'=>trim((string)($_POST['district']??''))?:null,'city'=>trim((string)($_POST['city']??''))?:null,'state'=>$state?:null,'postal'=>$postal,'latitude'=>$latitude,'latitude2'=>$latitude,'longitude'=>$longitude,'phone'=>trim((string)($_POST['phone']??''))?:null,'whatsapp'=>trim((string)($_POST['whatsapp']??''))?:null,'email'=>$email?:null,'instagram'=>ltrim(trim((string)($_POST['instagram']??'')),'@')?:null,'facebook'=>$urls['facebook'],'tiktok'=>ltrim(trim((string)($_POST['tiktok']??'')),'@')?:null,'website'=>$urls['website'],'map'=>$urls['map_url'],'amenities'=>json_encode($amenities,JSON_UNESCAPED_UNICODE),'payments'=>json_encode($payments,JSON_UNESCAPED_UNICODE),'notes'=>mb_substr(trim((string)($_POST['public_notes']??'')),0,500)?:null,'primary'=>$primary,'active'=>$active,'id'=>$id,'t'=>$t];
        $pdo->beginTransaction();try{if($primary)$pdo->prepare('UPDATE units SET is_primary=0 WHERE tenant_id=:t AND id<>:id')->execute(['t'=>$t,'id'=>$id]);$pdo->prepare('UPDATE units SET name=:n,address=:a,address_number=:number,address_complement=:complement,district=:district,city=:city,state=:state,postal_code=:postal,latitude=:latitude,longitude=:longitude,geocoded_at=IF(:latitude2 IS NULL,NULL,NOW()),phone=:phone,whatsapp=:whatsapp,email=:email,instagram=:instagram,facebook=:facebook,tiktok=:tiktok,website=:website,map_url=:map,amenities=:amenities,payment_methods=:payments,public_notes=:notes,is_primary=:primary,active=:active,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute($data);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('UNIT_UPDATED','units',$id,$old,['name'=>$name,'public_profile'=>true,'geocoded'=>$latitude!==null]);header('Location: '.($settings?'/settings/unit':'/units/'.$id.'/edit'));exit;
    }

    public function deactivate(string $id):void
    {
        ModuleService::require('multiunit');Authorization::require('units.manage');CSRF::enforce();$t=TenantContext::id();$uid=(int)$id;$pdo=Database::connection();$q=$pdo->prepare('SELECT * FROM units WHERE id=:id AND tenant_id=:t');$q->execute(['id'=>$uid,'t'=>$t]);$old=$q->fetch();if(!$old)HttpException::abort(404,'Unidade não encontrada.');$pdo->beginTransaction();try{$pdo->prepare('UPDATE units SET active=0,is_primary=0,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['id'=>$uid,'t'=>$t]);$pdo->prepare('UPDATE professionals SET unit_id=NULL,updated_at=NOW() WHERE tenant_id=:t AND unit_id=:id')->execute(['t'=>$t,'id'=>$uid]);if($old['is_primary'])$pdo->prepare('UPDATE units SET is_primary=1 WHERE tenant_id=:t AND active=1 ORDER BY id LIMIT 1')->execute(['t'=>$t]);$pdo->commit();Audit::log('UNIT_DEACTIVATED','units',$uid,$old);}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}header('Location: /units');exit;
    }
}
