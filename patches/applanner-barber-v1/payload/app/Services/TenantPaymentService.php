<?php
namespace App\Services;

use App\Core\{Database, Encryption};

final class TenantPaymentService
{
    public function providers(): array
    {
        return [
            'mercadopago' => [
                'name' => 'Mercado Pago',
                'available' => true,
                'auth_type' => 'api_credentials',
                'supports_pix' => true,
                'supports_card' => true,
                'note' => 'Pix e cartão tokenizado via API oficial. O Access Token e o segredo do webhook são armazenados criptografados; a Public Key pode ser usada no navegador para tokenização.',
            ],
            'asaas' => [
                'name' => 'Asaas',
                'available' => false,
                'auth_type' => 'api_credentials',
                'supports_pix' => false,
                'supports_card' => false,
                'note' => 'Adapter reservado. Exige credenciais e homologação antes de ser ativado.',
            ],
            'efi' => [
                'name' => 'Efí / Gerencianet',
                'available' => false,
                'auth_type' => 'api_credentials',
                'supports_pix' => false,
                'supports_card' => false,
                'note' => 'Adapter reservado. Exige certificado/credenciais oficiais e homologação.',
            ],
            'inter' => [
                'name' => 'Banco Inter',
                'available' => false,
                'auth_type' => 'api_credentials',
                'supports_pix' => false,
                'supports_card' => false,
                'note' => 'Adapter reservado. Disponibilidade depende do contrato/API da instituição.',
            ],
        ];
    }

    public function connections(int $tenantId): array
    {
        $q = Database::connection()->prepare(
            'SELECT id,tenant_id,provider,display_name,environment,auth_type,status,last_tested_at,last_sync_at,last_error_code,created_at,updated_at
             FROM tenant_payment_connections WHERE tenant_id=:tenant ORDER BY provider,environment'
        );
        $q->execute(['tenant' => $tenantId]);
        return $q->fetchAll() ?: [];
    }

    public function connected(int $tenantId, string $provider = 'mercadopago'): ?array
    {
        $q = Database::connection()->prepare(
            "SELECT * FROM tenant_payment_connections
             WHERE tenant_id=:tenant AND provider=:provider AND status='connected'
             ORDER BY (environment='production') DESC,id DESC LIMIT 1"
        );
        $q->execute(['tenant' => $tenantId, 'provider' => $provider]);
        $row = $q->fetch();
        return $row ?: null;
    }

    public function saveMercadoPago(
        int $tenantId,
        string $environment,
        string $accessToken,
        string $webhookSecret,
        string $publicKey,
        ?int $userId
    ): array {
        if (!in_array($environment, ['sandbox', 'production'], true)) {
            throw new \InvalidArgumentException('Ambiente inválido.');
        }
        if (!preg_match('/^(APP_USR-|TEST-)[A-Za-z0-9_-]{10,}$/', $accessToken)) {
            throw new \InvalidArgumentException('Access Token do Mercado Pago inválido.');
        }
        if (strlen($webhookSecret) < 16) {
            throw new \InvalidArgumentException('Informe o segredo de assinatura do webhook.');
        }
        $publicKey = trim($publicKey);
        if (strlen($publicKey) < 20 || !preg_match('/^[A-Za-z0-9_-]+$/', $publicKey)) {
            throw new \InvalidArgumentException('Public Key do Mercado Pago inválida.');
        }
        if ($environment === 'sandbox' && !str_starts_with($accessToken, 'TEST-')) {
            throw new \InvalidArgumentException('No Sandbox use uma credencial TEST-.');
        }
        if ($environment === 'production' && str_starts_with($accessToken, 'TEST-')) {
            throw new \InvalidArgumentException('Credencial de teste não pode ser salva como Produção.');
        }

        $provider = new MercadoPagoProvider($accessToken);
        $identity = $provider->testConnection();
        $credentialPayload = Encryption::encrypt([
            'access_token' => $accessToken,
            'webhook_secret' => $webhookSecret,
        ]);
        $metadata = json_encode([
            'user_id' => $identity['id'] ?? null,
            'nickname' => $identity['nickname'] ?? null,
            'public_key' => $publicKey,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);

        $pdo = Database::connection();
        $q = $pdo->prepare(
            "INSERT INTO tenant_payment_connections
             (tenant_id,provider,display_name,environment,auth_type,credentials_encrypted,metadata_json,status,last_tested_at,last_sync_at,last_error_code,created_by,created_at,updated_at)
             VALUES(:tenant,'mercadopago','Mercado Pago',:environment,'api_credentials',:credentials,:metadata,'connected',NOW(),NOW(),NULL,:user,NOW(),NOW())
             ON DUPLICATE KEY UPDATE
               credentials_encrypted=VALUES(credentials_encrypted),metadata_json=VALUES(metadata_json),status='connected',last_tested_at=NOW(),last_sync_at=NOW(),last_error_code=NULL,updated_at=NOW()"
        );
        $q->execute([
            'tenant' => $tenantId,
            'environment' => $environment,
            'credentials' => $credentialPayload,
            'metadata' => $metadata,
            'user' => $userId,
        ]);

        return ['provider' => 'mercadopago', 'environment' => $environment, 'identity' => $identity];
    }

    public function disconnect(int $tenantId, int $connectionId): void
    {
        $q = Database::connection()->prepare(
            "UPDATE tenant_payment_connections SET status='disabled',credentials_encrypted=NULL,updated_at=NOW()
             WHERE id=:id AND tenant_id=:tenant"
        );
        $q->execute(['id' => $connectionId, 'tenant' => $tenantId]);
        if (!$q->rowCount()) {
            throw new \DomainException('Integração não encontrada.');
        }
    }

    public function createPix(
        int $tenantId,
        string $referenceType,
        int $referenceId,
        float $amount,
        string $payerEmail,
        int $expirationMinutes = 10
    ): array {
        $connection = $this->connected($tenantId, 'mercadopago');
        if (!$connection) {
            throw new \DomainException('Nenhum provedor Pix automático está conectado.');
        }
        $credentials = $this->credentials($connection);
        $provider = new MercadoPagoProvider((string)$credentials['access_token']);
        $amount = round($amount, 2);
        if ($amount <= 0) {
            throw new \InvalidArgumentException('Valor da cobrança inválido.');
        }
        if (!filter_var($payerEmail, FILTER_VALIDATE_EMAIL)) {
            throw new \InvalidArgumentException('Para Pix automático, informe um e-mail válido.');
        }

        $pdo = Database::connection();
        $idempotency = 'arena-' . $referenceType . '-' . $referenceId . '-' . substr(hash('sha256', $tenantId . '|' . $amount), 0, 24);
        $existing = $pdo->prepare('SELECT * FROM tenant_payment_transactions WHERE tenant_id=:tenant AND idempotency_key=:key LIMIT 1');
        $existing->execute(['tenant' => $tenantId, 'key' => $idempotency]);
        $row = $existing->fetch();
        if ($row && in_array($row['status'], ['created', 'pending', 'paid'], true)) {
            return $row;
        }

        $external = 'ARENA-' . strtoupper(substr($referenceType, 0, 8)) . '-' . $referenceId . '-' . strtoupper(bin2hex(random_bytes(4)));
        $expiresAt = (new \DateTimeImmutable('+' . max(1, $expirationMinutes) . ' minutes'))->format('Y-m-d H:i:s');
        $hours = max(1, (int)ceil(max(1, $expirationMinutes) / 60));

        $pdo->beginTransaction();
        try {
            if ($row) {
                $txId = (int)$row['id'];
                $pdo->prepare(
                    "UPDATE tenant_payment_transactions SET status='created',external_reference=:external,gross_amount=:amount,net_amount=:amount2,expires_at=:expires,updated_at=NOW()
                     WHERE id=:id AND tenant_id=:tenant"
                )->execute(['external' => $external, 'amount' => $amount, 'amount2' => $amount, 'expires' => $expiresAt, 'id' => $txId, 'tenant' => $tenantId]);
            } else {
                $pdo->prepare(
                    "INSERT INTO tenant_payment_transactions
                     (tenant_id,connection_id,reference_type,reference_id,external_reference,method,gross_amount,fee_amount,net_amount,status,expires_at,idempotency_key,created_at,updated_at)
                     VALUES(:tenant,:connection,:type,:reference,:external,'pix',:amount,0,:net,'created',:expires,:key,NOW(),NOW())"
                )->execute([
                    'tenant' => $tenantId,
                    'connection' => $connection['id'],
                    'type' => $referenceType,
                    'reference' => $referenceId,
                    'external' => $external,
                    'amount' => $amount,
                    'net' => $amount,
                    'expires' => $expiresAt,
                    'key' => $idempotency,
                ]);
                $txId = (int)$pdo->lastInsertId();
            }
            $pdo->commit();
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            throw $e;
        }

        try {
            $order = $provider->createPixOrder([
                'amount' => $amount,
                'external_reference' => $external,
                'payer_email' => $payerEmail,
                'expiration_hours' => $hours,
                'idempotency_key' => $idempotency,
            ]);
            $status = in_array($order['status'] ?? '', ['processed'], true) ? 'paid' : 'pending';
            $pdo->prepare(
                "UPDATE tenant_payment_transactions
                 SET provider_transaction_id=:provider_id,status=:status,pix_qr_code=:qr,pix_copy_paste=:copy,checkout_url=:url,updated_at=NOW()
                 WHERE id=:id AND tenant_id=:tenant"
            )->execute([
                'provider_id' => $order['order_id'] ?? null,
                'status' => $status,
                'qr' => $order['qr_code_base64'] ?? null,
                'copy' => $order['qr_code'] ?? null,
                'url' => $order['ticket_url'] ?? null,
                'id' => $txId,
                'tenant' => $tenantId,
            ]);
        } catch (\Throwable $e) {
            $pdo->prepare(
                "UPDATE tenant_payment_transactions SET status='failed',updated_at=NOW() WHERE id=:id AND tenant_id=:tenant"
            )->execute(['id' => $txId, 'tenant' => $tenantId]);
            throw $e;
        }

        $q = $pdo->prepare('SELECT * FROM tenant_payment_transactions WHERE id=:id AND tenant_id=:tenant');
        $q->execute(['id' => $txId, 'tenant' => $tenantId]);
        return $q->fetch() ?: [];
    }


    public function supportsCard(array $connection): bool
    {
        if (($connection['provider'] ?? '') !== 'mercadopago' || ($connection['status'] ?? '') !== 'connected') return false;
        $meta = json_decode((string)($connection['metadata_json'] ?? ''), true);
        return is_array($meta) && !empty($meta['public_key']);
    }

    public function publicCardConfig(int $tenantId): ?array
    {
        $connection = $this->connected($tenantId, 'mercadopago');
        if (!$connection || !$this->supportsCard($connection)) return null;
        $meta = json_decode((string)($connection['metadata_json'] ?? ''), true) ?: [];
        $key = trim((string)($meta['public_key'] ?? ''));
        if ($key === '') return null;
        return [
            'provider' => 'mercadopago',
            'public_key' => $key,
            'environment' => (string)($connection['environment'] ?? 'sandbox'),
        ];
    }

    public function createCard(
        int $tenantId,
        string $referenceType,
        int $referenceId,
        float $amount,
        string $payerEmail,
        array $formData
    ): array {
        $connection = $this->connected($tenantId, 'mercadopago');
        if (!$connection || !$this->supportsCard($connection)) {
            throw new \DomainException('Pagamento por cartão não está configurado nesta Arena.');
        }
        $amount = round($amount, 2);
        if ($amount <= 0) throw new \InvalidArgumentException('Valor da cobrança inválido.');
        if (!filter_var($payerEmail, FILTER_VALIDATE_EMAIL)) throw new \InvalidArgumentException('Informe um e-mail válido.');
        $token = trim((string)($formData['token'] ?? ''));
        $method = trim((string)($formData['payment_method_id'] ?? ''));
        $installments = max(1, min(24, (int)($formData['installments'] ?? 1)));
        $issuer = trim((string)($formData['issuer_id'] ?? ''));
        $attempt = trim((string)($formData['attempt_id'] ?? ''));
        if ($token === '' || $method === '') throw new \InvalidArgumentException('Token do cartão ou bandeira ausente.');
        if ($attempt === '') $attempt = bin2hex(random_bytes(12));

        $pdo = Database::connection();
        $idempotency = 'arena-card-' . substr(hash('sha256', $tenantId . '|' . $referenceType . '|' . $referenceId . '|' . $amount . '|' . $attempt), 0, 64);
        $existing = $pdo->prepare('SELECT * FROM tenant_payment_transactions WHERE tenant_id=:tenant AND idempotency_key=:key LIMIT 1');
        $existing->execute(['tenant'=>$tenantId,'key'=>$idempotency]);
        $row = $existing->fetch();
        if ($row) return $row;

        $credentials = $this->credentials($connection);
        $provider = new MercadoPagoProvider((string)$credentials['access_token']);
        $external = 'ARENA-CARD-' . $referenceId . '-' . strtoupper(bin2hex(random_bytes(4)));
        $app = require dirname(__DIR__,2) . '/config/app.php';
        $tq=$pdo->prepare('SELECT public_slug,public_short_code FROM tenants WHERE id=:tenant');
        $tq->execute(['tenant'=>$tenantId]); $tenant=$tq->fetch()?:[];
        $slug=(string)($tenant['public_slug']?:$tenant['public_short_code']??'');
        $notificationUrl=rtrim((string)($app['url']??''),'/').'/webhooks/arena/mercadopago/'.rawurlencode($slug);

        $pdo->prepare(
            "INSERT INTO tenant_payment_transactions
             (tenant_id,connection_id,reference_type,reference_id,external_reference,method,gross_amount,fee_amount,net_amount,status,idempotency_key,created_at,updated_at)
             VALUES(:tenant,:connection,:type,:reference,:external,'card',:amount,0,:net,'created',:key,NOW(),NOW())"
        )->execute(['tenant'=>$tenantId,'connection'=>$connection['id'],'type'=>$referenceType,'reference'=>$referenceId,'external'=>$external,'amount'=>$amount,'net'=>$amount,'key'=>$idempotency]);
        $txId=(int)$pdo->lastInsertId();
        try {
            $idType=trim((string)($formData['payer']['identification']['type']??$formData['identification_type']??''));
            $idNumber=preg_replace('/\D/','',(string)($formData['payer']['identification']['number']??$formData['identification_number']??''))??'';
            $remote=$provider->createTokenizedCardPayment([
                'amount'=>$amount,'token'=>$token,'payment_method_id'=>$method,'installments'=>$installments,
                'issuer_id'=>$issuer!==''?$issuer:null,'payer_email'=>$payerEmail,
                'identification'=>$idType!==''&&$idNumber!==''?['type'=>$idType,'number'=>$idNumber]:null,
                'external_reference'=>$external,'notification_url'=>$notificationUrl,'idempotency_key'=>$idempotency,
                'description'=>'Sinal de reserva Arena #'.$referenceId,
            ]);
            $mapped=(new ArenaPaymentReconciliationService())->mapStatus((string)($remote['status']??''));
            $fee=round((float)($remote['fee_amount']??0),2); $net=round((float)($remote['net_received_amount']??max(0,$amount-$fee)),2);
            if($net<=0 && $mapped==='paid') $net=round(max(0,$amount-$fee),2);
            $pdo->prepare("UPDATE tenant_payment_transactions SET provider_transaction_id=:provider,status=:status,fee_amount=:fee,net_amount=:net,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['provider'=>$remote['id']??null,'status'=>$mapped,'fee'=>$fee,'net'=>$net,'id'=>$txId,'tenant'=>$tenantId]);
            (new ArenaPaymentReconciliationService())->apply($txId,$mapped,$fee,$net);
        } catch (\Throwable $e) {
            $pdo->prepare("UPDATE tenant_payment_transactions SET status='failed',updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['id'=>$txId,'tenant'=>$tenantId]);
            throw $e;
        }
        $q=$pdo->prepare('SELECT * FROM tenant_payment_transactions WHERE id=:id AND tenant_id=:tenant');$q->execute(['id'=>$txId,'tenant'=>$tenantId]);
        return $q->fetch()?:[];
    }

    public function createRecurringSubscription(int $tenantId,string $referenceType,int $referenceId,float $amount,string $payerEmail,int $cycleMonths=1): array
    {
        $connection=$this->connected($tenantId,'mercadopago');
        if(!$connection)throw new \DomainException('Nenhum provedor de cobrança recorrente está conectado.');
        if(!filter_var($payerEmail,FILTER_VALIDATE_EMAIL))throw new \InvalidArgumentException('O cliente precisa ter um e-mail válido para cobrança automática.');
        $amount=round($amount,2);if($amount<=0)throw new \InvalidArgumentException('Valor recorrente inválido.');$cycleMonths=max(1,min(12,$cycleMonths));
        $pdo=Database::connection();$key='barber-recurring-'.substr(hash('sha256',$tenantId.'|'.$referenceType.'|'.$referenceId.'|'.$amount.'|'.$cycleMonths),0,64);
        $q=$pdo->prepare('SELECT * FROM tenant_recurring_subscriptions WHERE tenant_id=:t AND idempotency_key=:k LIMIT 1');$q->execute(['t'=>$tenantId,'k'=>$key]);if($row=$q->fetch())return $row;
        $credentials=$this->credentials($connection);$provider=new MercadoPagoProvider((string)$credentials['access_token']);$tq=$pdo->prepare('SELECT name,public_slug,public_short_code FROM tenants WHERE id=:t');$tq->execute(['t'=>$tenantId]);$tenant=$tq->fetch()?:[];$slug=(string)($tenant['public_slug']?:($tenant['public_short_code']??''));$app=require dirname(__DIR__,2).'/config/app.php';$external='BARBER-MEMBERSHIP-'.$referenceId.'-'.strtoupper(substr(hash('sha256',$key),0,8));
        $remote=$provider->createSubscription(['reason'=>'Clube / mensalidade '.($tenant['name']??'Barbearia'),'external_reference'=>$external,'payer_email'=>$payerEmail,'back_url'=>rtrim((string)($app['url']??''),'/').'/a/'.rawurlencode($slug),'amount'=>$amount,'frequency'=>$cycleMonths,'idempotency_key'=>$key]);
        $pdo->prepare("INSERT INTO tenant_recurring_subscriptions(tenant_id,connection_id,reference_type,reference_id,external_reference,provider_subscription_id,amount,cycle_months,status,checkout_url,idempotency_key,created_at,updated_at)VALUES(:t,:c,:type,:rid,:external,:provider,:amount,:cycle,'pending',:url,:key,NOW(),NOW())")->execute(['t'=>$tenantId,'c'=>$connection['id'],'type'=>$referenceType,'rid'=>$referenceId,'external'=>$external,'provider'=>$remote['reference']??null,'amount'=>$amount,'cycle'=>$cycleMonths,'url'=>$remote['init_point']??null,'key'=>$key]);
        $id=(int)$pdo->lastInsertId();$q=$pdo->prepare('SELECT * FROM tenant_recurring_subscriptions WHERE id=:id');$q->execute(['id'=>$id]);return $q->fetch()?:[];
    }

    public function cancelRecurringSubscription(int $tenantId,string $referenceType,int $referenceId): void
    {
        $pdo=Database::connection();$q=$pdo->prepare("SELECT rs.*,pc.credentials_encrypted FROM tenant_recurring_subscriptions rs JOIN tenant_payment_connections pc ON pc.id=rs.connection_id WHERE rs.tenant_id=:t AND rs.reference_type=:type AND rs.reference_id=:rid AND rs.status<>'cancelled' ORDER BY rs.id DESC LIMIT 1");$q->execute(['t'=>$tenantId,'type'=>$referenceType,'rid'=>$referenceId]);$row=$q->fetch();if(!$row)return;
        if(!empty($row['provider_subscription_id'])&&!empty($row['credentials_encrypted'])){try{$cred=Encryption::decrypt((string)$row['credentials_encrypted']);(new MercadoPagoProvider((string)($cred['access_token']??'')))->cancelSubscription((string)$row['provider_subscription_id']);}catch(\Throwable $e){error_log('[ApPlanner Barber] cancel recurring: '.mb_substr($e->getMessage(),0,180));}}
        $pdo->prepare("UPDATE tenant_recurring_subscriptions SET status='cancelled',updated_at=NOW() WHERE id=:id AND tenant_id=:t")->execute(['id'=>$row['id'],'t'=>$tenantId]);
    }

    public function credentials(array $connection): array
    {
        $encrypted = (string)($connection['credentials_encrypted'] ?? '');
        if ($encrypted === '') {
            throw new \RuntimeException('Credenciais da integração não estão disponíveis.');
        }
        return Encryption::decrypt($encrypted);
    }
}
