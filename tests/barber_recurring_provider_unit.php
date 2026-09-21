<?php
declare(strict_types=1);
$root=dirname(__DIR__);
spl_autoload_register(static function(string $class)use($root):void{$prefix='App\\';if(!str_starts_with($class,$prefix))return;$file=$root.'/app/'.str_replace('\\','/',substr($class,strlen($prefix))).'.php';if(is_file($file))require_once $file;});
use App\Services\MercadoPagoProvider;
$calls=[];$transport=static function(string $method,string $path,array $body,string $idempotency,string $token)use(&$calls):array{$calls[]=compact('method','path','body','idempotency');if(str_starts_with($path,'/authorized_payments/'))return ['id'=>'auth-1','external_reference'=>'BARBER-MEMBERSHIP-9-ABC','transaction_amount'=>89.9,'status'=>'processed','payment'=>['id'=>'pay-1','status'=>'approved','payment_method_id'=>'visa']];if(str_starts_with($path,'/v1/payments/search?'))return ['paging'=>['total'=>1],'results'=>[['id'=>'pay-1','external_reference'=>'BARBER-MEMBERSHIP-9-ABC','transaction_amount'=>89.9,'status'=>'approved']]];if($method==='POST'&&$path==='/preapproval')return ['id'=>'sub-1','status'=>'pending','init_point'=>'https://example.invalid/checkout'];throw new RuntimeException('Chamada inesperada: '.$method.' '.$path);};
$mp=new MercadoPagoProvider('TEST-12345678901234567890',$transport);
$a=$mp->getAuthorizedPayment('auth-1');if(($a['payment']['status']??'')!=='approved')throw new RuntimeException('Pagamento autorizado não foi lido.');
$list=$mp->searchPaymentsByExternalReference('BARBER-MEMBERSHIP-9-ABC',120);if(count($list)!==1||($list[0]['id']??'')!=='pay-1')throw new RuntimeException('Busca por external_reference falhou.');
$sub=$mp->createSubscription(['reason'=>'Clube Barber','external_reference'=>'BARBER-MEMBERSHIP-9-ABC','payer_email'=>'cliente@example.com','back_url'=>'https://applanner.com.br/a/demo','amount'=>89.90,'frequency'=>1,'idempotency_key'=>'unit-1']);if(($sub['reference']??'')!=='sub-1')throw new RuntimeException('Criação de assinatura falhou.');
$searchCall=null;foreach($calls as $call)if(str_starts_with($call['path'],'/v1/payments/search?'))$searchCall=$call;if(!$searchCall||!str_contains($searchCall['path'],'external_reference=BARBER-MEMBERSHIP-9-ABC'))throw new RuntimeException('external_reference não foi enviado na consulta.');
echo "barber recurring provider unit: OK\n";
