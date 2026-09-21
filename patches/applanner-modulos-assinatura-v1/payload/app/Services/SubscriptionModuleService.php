<?php
namespace App\Services;

use App\Core\{Database,Encryption};

final class SubscriptionModuleService
{
    public function augmentQuote(int $tenantId,string $cycle,array $quote):array
    {
        $months=$this->cycleMonths($cycle);
        $targetPlanId=(int)($quote['plan']['id']??0);
        $monthly=$this->mergedAddonMonthlyForPlan($tenantId,$targetPlanId);
        $addon=round($monthly*$months,2);
        $quote['base_subtotal']=(float)($quote['subtotal']??0);
        $quote['base_total']=(float)($quote['total']??0);
        $quote['addon_monthly_total']=$monthly;
        $quote['addon_total']=$addon;
        $quote['subtotal']=round((float)$quote['subtotal']+$addon,2);
        $quote['total']=round((float)$quote['total']+$addon,2);
        return $quote;
    }

    public function breakdown(int $tenantId):array
    {
        $pdo=Database::connection();
        $q=$pdo->prepare("SELECT s.*,p.name plan_name FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.tenant_id=:t ORDER BY s.id DESC LIMIT 1");
        $q->execute(['t'=>$tenantId]);$s=$q->fetch();
        if(!$s)return ['subscription'=>null,'base'=>0.0,'addons'=>0.0,'total'=>0.0,'monthly_addons'=>0.0,'items'=>[],'legacy_monthly'=>0.0];
        $months=$this->cycleMonths((string)$s['billing_cycle']);
        $items=$pdo->prepare("SELECT ta.id,ta.monthly_price,ta.billing_mode,ta.status,ta.next_billing_at,m.name,m.slug FROM tenant_module_addons ta JOIN modules m ON m.id=ta.module_id WHERE ta.tenant_id=:t AND ta.status='active' ORDER BY m.name");
        $items->execute(['t'=>$tenantId]);$rows=$items->fetchAll();
        $merged=0.0;$legacy=0.0;
        foreach($rows as $row){if(($row['billing_mode']??'separate')==='merged_subscription')$merged+=(float)$row['monthly_price'];else $legacy+=(float)$row['monthly_price'];}
        $base=(float)($s['base_contracted_price']??$s['contracted_price']??0);
        $addonCycle=round($merged*$months,2);
        return ['subscription'=>$s,'base'=>$base,'addons'=>$addonCycle,'total'=>round($base+$addonCycle,2),'monthly_addons'=>round($merged,2),'legacy_monthly'=>round($legacy,2),'items'=>$rows,'months'=>$months];
    }

    public function activateApprovedRequest(int $requestId,int $tenantId,int $actorUserId):array
    {
        $pdo=Database::connection();
        $q=$pdo->prepare("SELECT mr.*,m.name module_name,m.slug module_slug FROM module_requests mr JOIN modules m ON m.id=mr.module_id WHERE mr.id=:id AND mr.tenant_id=:t AND mr.status IN('approved','payment_failed')");
        $q->execute(['id'=>$requestId,'t'=>$tenantId]);$request=$q->fetch();
        if(!$request)throw new \DomainException('Solicitação não está pronta para ser incorporada à assinatura.');
        if((float)$request['quoted_monthly_price']<=0)throw new \DomainException('O módulo precisa possuir valor mensal válido.');
        if(ModuleService::has((string)$request['module_slug'],$tenantId))throw new \DomainException('Este módulo já está disponível para sua empresa.');

        $sub=$this->subscription($tenantId);
        if(!$sub||!in_array((string)$sub['status'],['trial','active','past_due'],true))throw new \DomainException('A empresa precisa possuir uma assinatura válida para incorporar módulos.');
        $months=$this->cycleMonths((string)$sub['billing_cycle']);
        $base=(float)($sub['base_contracted_price']??$sub['contracted_price']??0);
        $currentMonthly=$this->mergedAddonMonthly($tenantId);
        $previous=round($base+$currentMonthly*$months,2);
        $newMonthly=round($currentMonthly+(float)$request['quoted_monthly_price'],2);
        $newTotal=round($base+$newMonthly*$months,2);
        if($newTotal<=0)throw new \DomainException('Não foi possível calcular o novo valor da assinatura.');

        $adjustment=$this->createAdjustment($tenantId,(int)$sub['id'],$requestId,null,'add',$previous,$newTotal,(float)$request['quoted_monthly_price'],$actorUserId);
        $providerChanged=false;$provider=null;$legacyRef=trim((string)($request['provider_reference']??''));
        try{
            [$provider,$mainRef]=$this->providerForSubscription($sub);
            if($provider&&$mainRef!==''){$provider->updateSubscriptionAmount($mainRef,$newTotal);$providerChanged=true;}
            if($provider&&$legacyRef!==''&&$legacyRef!==$mainRef){try{$provider->cancelSubscription($legacyRef);}catch(\Throwable){/* cobrança legada pendente também será neutralizada localmente */}}
            $pdo->beginTransaction();
            try{
                $pdo->prepare("INSERT INTO tenant_module_addons(tenant_id,module_id,module_request_id,monthly_price,status,billing_mode,provider,provider_reference,started_at,next_billing_at,created_at,updated_at) VALUES(:t,:m,:r,:price,'active','merged_subscription',:provider,:ref,NOW(),:next,NOW(),NOW()) ON DUPLICATE KEY UPDATE module_request_id=VALUES(module_request_id),monthly_price=VALUES(monthly_price),status='active',billing_mode='merged_subscription',provider=VALUES(provider),provider_reference=VALUES(provider_reference),started_at=COALESCE(started_at,NOW()),next_billing_at=VALUES(next_billing_at),cancelled_at=NULL,updated_at=NOW()")
                    ->execute(['t'=>$tenantId,'m'=>$request['module_id'],'r'=>$requestId,'price'=>$request['quoted_monthly_price'],'provider'=>$mainRef!==''?'mercadopago':null,'ref'=>$mainRef!==''?$mainRef:null,'next'=>$sub['next_billing_at']??null]);
                $addonId=(int)$pdo->lastInsertId();if($addonId===0){$a=$pdo->prepare('SELECT id FROM tenant_module_addons WHERE tenant_id=:t AND module_id=:m');$a->execute(['t'=>$tenantId,'m'=>$request['module_id']]);$addonId=(int)$a->fetchColumn();}
                $pdo->prepare('INSERT INTO tenant_modules(tenant_id,module_id,enabled) VALUES(:t,:m,1) ON DUPLICATE KEY UPDATE enabled=1')->execute(['t'=>$tenantId,'m'=>$request['module_id']]);
                $pdo->prepare("UPDATE module_requests SET status='active',provider_reference=:ref,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['ref'=>$mainRef!==''?$mainRef:null,'id'=>$requestId,'t'=>$tenantId]);
                $pdo->prepare("UPDATE payments SET status='cancelled',updated_at=NOW() WHERE tenant_id=:t AND purpose='module_addon' AND reference_id=:r AND status='pending'")->execute(['t'=>$tenantId,'r'=>$requestId]);
                $pdo->prepare('UPDATE subscriptions SET base_contracted_price=:base,addon_contracted_price=:addon,contracted_price=:total,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['base'=>$base,'addon'=>round($newMonthly*$months,2),'total'=>$newTotal,'id'=>$sub['id'],'t'=>$tenantId]);
                $pdo->prepare("UPDATE subscription_module_adjustments SET module_addon_id=:addon,status='applied',provider=:provider,provider_reference=:ref,applied_at=NOW(),updated_at=NOW() WHERE id=:id")->execute(['addon'=>$addonId,'provider'=>$mainRef!==''?'mercadopago':null,'ref'=>$mainRef!==''?$mainRef:null,'id'=>$adjustment]);
                $pdo->commit();
            }catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
        }catch(\Throwable $e){
            $sync='failed';
            if($providerChanged&&$provider){try{$provider->updateSubscriptionAmount((string)$sub['provider_subscription_id'],$previous);}catch(\Throwable){$sync='sync_required';}}
            $this->failAdjustment($adjustment,$sync,$e);
            throw $e;
        }
        return ['module_name'=>$request['module_name'],'monthly_price'=>(float)$request['quoted_monthly_price'],'previous_total'=>$previous,'new_total'=>$newTotal,'billing_cycle'=>$sub['billing_cycle']];
    }

    public function cancelAddon(int $addonId,int $tenantId,int $actorUserId):array
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT ta.*,m.name module_name,m.slug module_slug FROM tenant_module_addons ta JOIN modules m ON m.id=ta.module_id WHERE ta.id=:id AND ta.tenant_id=:t AND ta.status='active'");$q->execute(['id'=>$addonId,'t'=>$tenantId]);$addon=$q->fetch();if(!$addon)throw new \DomainException('Módulo adicional ativo não encontrado.');
        if(($addon['billing_mode']??'separate')!=='merged_subscription')return $this->cancelLegacyAddon($addon,$tenantId);
        $sub=$this->subscription($tenantId);if(!$sub)throw new \DomainException('Assinatura não encontrada.');$months=$this->cycleMonths((string)$sub['billing_cycle']);$base=(float)($sub['base_contracted_price']??$sub['contracted_price']??0);$currentMonthly=$this->mergedAddonMonthly($tenantId);$previous=round($base+$currentMonthly*$months,2);$newMonthly=max(0,round($currentMonthly-(float)$addon['monthly_price'],2));$newTotal=round($base+$newMonthly*$months,2);
        $adjustment=$this->createAdjustment($tenantId,(int)$sub['id'],(int)($addon['module_request_id']??0)?:null,$addonId,'remove',$previous,$newTotal,(float)$addon['monthly_price'],$actorUserId);$providerChanged=false;$provider=null;
        try{[$provider,$mainRef]=$this->providerForSubscription($sub);if($provider&&$mainRef!==''){$provider->updateSubscriptionAmount($mainRef,$newTotal);$providerChanged=true;}$pdo->beginTransaction();try{$pdo->prepare("UPDATE tenant_module_addons SET status='cancelled',cancelled_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>$addonId,'t'=>$tenantId]);$pdo->prepare('DELETE FROM tenant_modules WHERE tenant_id=:t AND module_id=:m')->execute(['t'=>$tenantId,'m'=>$addon['module_id']]);$pdo->prepare("UPDATE module_requests SET status='cancelled',updated_at=NOW() WHERE tenant_id=:t AND module_id=:m AND status='active'")->execute(['t'=>$tenantId,'m'=>$addon['module_id']]);$pdo->prepare('UPDATE subscriptions SET base_contracted_price=:base,addon_contracted_price=:addon,contracted_price=:total,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['base'=>$base,'addon'=>round($newMonthly*$months,2),'total'=>$newTotal,'id'=>$sub['id'],'t'=>$tenantId]);$pdo->prepare("UPDATE subscription_module_adjustments SET status='applied',provider=:provider,provider_reference=:ref,applied_at=NOW(),updated_at=NOW() WHERE id=:id")->execute(['provider'=>$mainRef!==''?'mercadopago':null,'ref'=>$mainRef!==''?$mainRef:null,'id'=>$adjustment]);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}}catch(\Throwable $e){$sync='failed';if($providerChanged&&$provider){try{$provider->updateSubscriptionAmount((string)$sub['provider_subscription_id'],$previous);}catch(\Throwable){$sync='sync_required';}}$this->failAdjustment($adjustment,$sync,$e);throw $e;}
        return ['module_name'=>$addon['module_name'],'previous_total'=>$previous,'new_total'=>$newTotal];
    }

    public function consolidateLegacy(int $tenantId,int $actorUserId,bool $apply=false):array
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT ta.*,m.name module_name FROM tenant_module_addons ta JOIN modules m ON m.id=ta.module_id WHERE ta.tenant_id=:t AND ta.status='active' AND COALESCE(ta.billing_mode,'separate')='separate' ORDER BY ta.id");$q->execute(['t'=>$tenantId]);$legacy=$q->fetchAll();$preview=$this->breakdown($tenantId);$preview['legacy_items']=$legacy;$preview['applied']=[];if(!$apply||!$legacy)return $preview;
        foreach($legacy as $item){$sub=$this->subscription($tenantId);if(!$sub)throw new \DomainException('Assinatura não encontrada.');$months=$this->cycleMonths((string)$sub['billing_cycle']);$base=(float)($sub['base_contracted_price']??$sub['contracted_price']??0);$currentMonthly=$this->mergedAddonMonthly($tenantId);$previous=round($base+$currentMonthly*$months,2);$newMonthly=round($currentMonthly+(float)$item['monthly_price'],2);$newTotal=round($base+$newMonthly*$months,2);$adjustment=$this->createAdjustment($tenantId,(int)$sub['id'],(int)($item['module_request_id']??0)?:null,(int)$item['id'],'consolidate',$previous,$newTotal,(float)$item['monthly_price'],$actorUserId);$providerChanged=false;$provider=null;
            try{[$provider,$mainRef]=$this->providerForSubscription($sub);if(!$provider||$mainRef==='')throw new \DomainException('A assinatura principal precisa estar conectada ao Mercado Pago para consolidar cobranças legadas.');$provider->updateSubscriptionAmount($mainRef,$newTotal);$providerChanged=true;$legacyRef=trim((string)($item['provider_reference']??''));if($legacyRef!==''&&$legacyRef!==$mainRef)$provider->cancelSubscription($legacyRef);$pdo->beginTransaction();try{$pdo->prepare("UPDATE tenant_module_addons SET billing_mode='merged_subscription',provider='mercadopago',provider_reference=:ref,next_billing_at=:next,updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['ref'=>$mainRef,'next'=>$sub['next_billing_at']??null,'id'=>$item['id'],'t'=>$tenantId]);$pdo->prepare('UPDATE subscriptions SET base_contracted_price=:base,addon_contracted_price=:addon,contracted_price=:total,updated_at=NOW() WHERE id=:id AND tenant_id=:t')->execute(['base'=>$base,'addon'=>round($newMonthly*$months,2),'total'=>$newTotal,'id'=>$sub['id'],'t'=>$tenantId]);$pdo->prepare("UPDATE subscription_module_adjustments SET status='applied',provider='mercadopago',provider_reference=:ref,applied_at=NOW(),updated_at=NOW() WHERE id=:id")->execute(['ref'=>$mainRef,'id'=>$adjustment]);$pdo->commit();$preview['applied'][]=['addon_id'=>(int)$item['id'],'module'=>$item['module_name'],'new_total'=>$newTotal];}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}}catch(\Throwable $e){$sync='failed';if($providerChanged&&$provider){try{$provider->updateSubscriptionAmount((string)$sub['provider_subscription_id'],$previous);}catch(\Throwable){$sync='sync_required';}}$this->failAdjustment($adjustment,$sync,$e);throw $e;}}
        return $preview;
    }

    private function cancelLegacyAddon(array $addon,int $tenantId):array
    {
        $pdo=Database::connection();$ref=trim((string)($addon['provider_reference']??''));if($ref!==''){$gateway=$this->gateway();if(!$gateway)throw new \DomainException('Mercado Pago indisponível para cancelar a cobrança antiga.');$provider=new MercadoPagoProvider(Encryption::decrypt($gateway['access_token_encrypted'])['value']??'');$provider->cancelSubscription($ref);}
        $pdo->beginTransaction();try{$pdo->prepare("UPDATE tenant_module_addons SET status='cancelled',cancelled_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>$addon['id'],'t'=>$tenantId]);$pdo->prepare('DELETE FROM tenant_modules WHERE tenant_id=:t AND module_id=:m')->execute(['t'=>$tenantId,'m'=>$addon['module_id']]);$pdo->prepare("UPDATE module_requests SET status='cancelled',updated_at=NOW() WHERE tenant_id=:t AND module_id=:m AND status='active'")->execute(['t'=>$tenantId,'m'=>$addon['module_id']]);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}return ['module_name'=>$addon['module_name'],'legacy'=>true];
    }

    private function subscription(int $tenantId):array|false{$q=Database::connection()->prepare('SELECT * FROM subscriptions WHERE tenant_id=:t ORDER BY id DESC LIMIT 1');$q->execute(['t'=>$tenantId]);return $q->fetch();}
    private function mergedAddonMonthly(int $tenantId):float{$q=Database::connection()->prepare("SELECT COALESCE(SUM(monthly_price),0) FROM tenant_module_addons WHERE tenant_id=:t AND status='active' AND COALESCE(billing_mode,'separate')='merged_subscription'");$q->execute(['t'=>$tenantId]);return round((float)$q->fetchColumn(),2);}
    private function mergedAddonMonthlyForPlan(int $tenantId,int $planId):float{if($planId<=0)return $this->mergedAddonMonthly($tenantId);$q=Database::connection()->prepare("SELECT COALESCE(SUM(ta.monthly_price),0) FROM tenant_module_addons ta LEFT JOIN plan_modules pm ON pm.plan_id=:p AND pm.module_id=ta.module_id AND pm.enabled=1 WHERE ta.tenant_id=:t AND ta.status='active' AND COALESCE(ta.billing_mode,'separate')='merged_subscription' AND pm.module_id IS NULL");$q->execute(['p'=>$planId,'t'=>$tenantId]);return round((float)$q->fetchColumn(),2);}
    private function cycleMonths(string $cycle):int{return ['monthly'=>1,'quarterly'=>3,'semiannual'=>6,'annual'=>12][$cycle]??1;}
    private function gateway():array|false{return Database::connection()->query("SELECT * FROM payment_gateways WHERE provider='mercadopago' AND active=1 AND last_test_status='validated' ORDER BY (environment='production') DESC,last_tested_at DESC LIMIT 1")->fetch();}
    private function providerForSubscription(array $sub):array{$ref=trim((string)($sub['provider_subscription_id']??''));if($ref==='')return [null,''];$gateway=$this->gateway();if(!$gateway)throw new \DomainException('Mercado Pago não está disponível para atualizar o valor da assinatura.');$token=Encryption::decrypt($gateway['access_token_encrypted'])['value']??'';return [new MercadoPagoProvider($token),$ref];}
    private function createAdjustment(int $tenantId,int $subscriptionId,?int $requestId,?int $addonId,string $action,float $previous,float $new,float $monthly,int $actor):int{$pdo=Database::connection();$public=bin2hex(random_bytes(16));$key=hash('sha256',implode('|',[$action,$tenantId,$subscriptionId,$requestId??0,$addonId??0,number_format($previous,2,'.',''),number_format($new,2,'.',''),microtime(true)]));$q=$pdo->prepare("INSERT INTO subscription_module_adjustments(public_id,tenant_id,subscription_id,module_request_id,module_addon_id,action,previous_amount,new_amount,addon_monthly_price,idempotency_key,status,created_by,created_at,updated_at) VALUES(:public,:t,:s,:r,:a,:action,:previous,:new,:monthly,:key,'pending',:u,NOW(),NOW())");$q->execute(['public'=>$public,'t'=>$tenantId,'s'=>$subscriptionId,'r'=>$requestId,'a'=>$addonId,'action'=>$action,'previous'=>$previous,'new'=>$new,'monthly'=>$monthly,'key'=>$key,'u'=>$actor?:null]);return (int)$pdo->lastInsertId();}
    private function failAdjustment(int $id,string $status,\Throwable $e):void{try{$code=mb_substr(preg_replace('/[^A-Za-z0-9 _.:\/-]/',' ',get_class($e).': '.$e->getMessage())??'erro',0,120);$q=Database::connection()->prepare('UPDATE subscription_module_adjustments SET status=:s,error_code=:e,updated_at=NOW() WHERE id=:id');$q->execute(['s'=>$status,'e'=>$code,'id'=>$id]);}catch(\Throwable){}}
}
