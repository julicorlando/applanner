<?php
declare(strict_types=1);
require_once dirname(__DIR__).'/app/Contracts/PaymentProviderInterface.php';
require_once dirname(__DIR__).'/app/Services/MercadoPagoProvider.php';

$captured=[];
$transport=static function(string $method,string $path,array $body,string $idempotency,string $token) use (&$captured):array{
    $captured=compact('method','path','body','idempotency','token');
    return ['id'=>'preapproval_test_123','status'=>'authorized','version'=>4,'auto_recurring'=>['transaction_amount'=>129.90]];
};
$p=new \App\Services\MercadoPagoProvider('TEST-1234567890ABCDEFGHIJ',$transport);
$r=$p->updateSubscriptionAmount('preapproval_test_123',129.90);
$ok=$captured['method']==='PUT'
    && $captured['path']==='/preapproval/preapproval_test_123'
    && abs((float)($captured['body']['auto_recurring']['transaction_amount']??0)-129.90)<0.001
    && ($captured['body']['auto_recurring']['currency_id']??'')==='BRL'
    && abs((float)$r['amount']-129.90)<0.001;
if(!$ok){fwrite(STDERR,"mercadopago subscription update unit: FALHOU\n");exit(1);}echo "mercadopago subscription update unit: OK\n";
