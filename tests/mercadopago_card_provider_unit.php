<?php
declare(strict_types=1);
if(PHP_SAPI!=='cli'){http_response_code(404);exit;}
$root=dirname(__DIR__);
spl_autoload_register(static function(string $class) use($root):void{$prefix='App\\';if(!str_starts_with($class,$prefix))return;$f=$root.'/app/'.str_replace('\\','/',substr($class,strlen($prefix))).'.php';if(is_file($f))require_once $f;});
try{
    $captured=[];
    $transport=static function(string $method,string $path,array $body,string $idempotency,string $token) use (&$captured):array{
        $captured=compact('method','path','body','idempotency','token');
        return ['id'=>'123456789','status'=>'approved','payment_method_id'=>'visa','payment_type_id'=>'credit_card','transaction_amount'=>45.00,'fee_details'=>[['amount'=>1.10],['amount'=>0.25]],'transaction_details'=>['net_received_amount'=>43.65]];
    };
    $provider=new \App\Services\MercadoPagoProvider('TEST-1234567890ABCDE',$transport);
    $r=$provider->createTokenizedCardPayment(['amount'=>45,'token'=>'card-token-test','payment_method_id'=>'visa','installments'=>1,'payer_email'=>'cliente@example.com','external_reference'=>'ARENA-1','idempotency_key'=>'idem-1']);
    if(($captured['method']??'')!=='POST'||($captured['path']??'')!=='/v1/payments')throw new RuntimeException('Endpoint/método incorreto.');
    if(($captured['idempotency']??'')!=='idem-1')throw new RuntimeException('Idempotência ausente.');
    if(($captured['body']['token']??'')!=='card-token-test')throw new RuntimeException('Token não enviado.');
    if(isset($captured['body']['card_number'])||isset($captured['body']['security_code']))throw new RuntimeException('Dados brutos de cartão não devem ir ao backend/provider wrapper.');
    if(abs((float)$r['fee_amount']-1.35)>0.001||abs((float)$r['net_received_amount']-43.65)>0.001)throw new RuntimeException('Conciliação de taxa/líquido incorreta.');
    echo "MERCADO PAGO CARD UNIT: OK\n";
}catch(Throwable $e){fwrite(STDERR,'MERCADO PAGO CARD UNIT: FALHOU — '.$e->getMessage()."\n");exit(1);}
