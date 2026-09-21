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
                'supports_card' => false,
                'note' => 'Pix via API oficial. O Access Token e o segredo do webhook são armazenados criptografados.',
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

    public function credentials(array $connection): array
    {
        $encrypted = (string)($connection['credentials_encrypted'] ?? '');
        if ($encrypted === '') {
            throw new \RuntimeException('Credenciais da integração não estão disponíveis.');
        }
        return Encryption::decrypt($encrypted);
    }
}
