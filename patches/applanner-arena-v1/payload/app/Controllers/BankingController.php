<?php
namespace App\Controllers;

use App\Core\{Audit, Authorization, Auth, CSRF, Database, HttpException, TenantContext, View};
use App\Services\{ModuleService, TenantPaymentService};

final class BankingController
{
    private function access(string $permission = 'banking.view'): int
    {
        ModuleService::require('banking_integrations');
        Authorization::require($permission);
        return TenantContext::id();
    }

    public function index(): void
    {
        $tenantId = $this->access('banking.view');
        $service = new TenantPaymentService();
        $q = Database::connection()->prepare(
            'SELECT * FROM tenant_payment_transactions WHERE tenant_id=:tenant ORDER BY id DESC LIMIT 100'
        );
        $q->execute(['tenant' => $tenantId]);
        $tq=Database::connection()->prepare('SELECT public_slug,public_short_code FROM tenants WHERE id=:tenant');$tq->execute(['tenant'=>$tenantId]);$tenant=$tq->fetch()?:[];
        $app=require dirname(__DIR__,2).'/config/app.php';$webhookSlug=(string)($tenant['public_slug']?:$tenant['public_short_code']);$webhookUrl=rtrim((string)($app['url']??''),'/').'/webhooks/arena/mercadopago/'.rawurlencode($webhookSlug);
        View::render('banking/index', [
            'title' => 'Bancos e Pagamentos',
            'providers' => $service->providers(),
            'connections' => $service->connections($tenantId),
            'transactions' => Authorization::allows('banking.transactions.view') ? ($q->fetchAll() ?: []) : [],
            'canManage' => Authorization::allows('banking.manage'),
            'webhookUrl' => $webhookUrl,
        ]);
    }

    public function connect(): void
    {
        $tenantId = $this->access('banking.manage');
        CSRF::enforce();
        $provider = (string)($_POST['provider'] ?? '');
        if ($provider !== 'mercadopago') {
            HttpException::abort(422, 'Esta instituição ainda não está disponível.');
        }
        $environment = (string)($_POST['environment'] ?? 'sandbox');
        $token = trim((string)($_POST['access_token'] ?? ''));
        $secret = trim((string)($_POST['webhook_secret'] ?? ''));
        try {
            $result = (new TenantPaymentService())->saveMercadoPago(
                $tenantId,
                $environment,
                $token,
                $secret,
                (int)(Auth::user()['id'] ?? 0) ?: null
            );
        } catch (\InvalidArgumentException|\DomainException $e) {
            HttpException::abort(422, $e->getMessage());
        } catch (\Throwable $e) {
            error_log('[ApPlanner Banking] Falha ao validar Mercado Pago tenant=' . $tenantId . ': ' . $e->getMessage());
            HttpException::abort(502, 'Não foi possível validar a conexão com o Mercado Pago. Verifique a credencial e tente novamente.');
        }
        Audit::log('BANK_CONNECTION_CREATED', 'tenant_payment_connections', null, null, [
            'provider' => $provider,
            'environment' => $environment,
            'connected' => true,
        ]);
        header('Location: /settings/banking?connected=1');
        exit;
    }

    public function disconnect(string $id): void
    {
        $tenantId = $this->access('banking.manage');
        CSRF::enforce();
        try {
            (new TenantPaymentService())->disconnect($tenantId, (int)$id);
        } catch (\DomainException $e) {
            HttpException::abort(404, $e->getMessage());
        }
        Audit::log('BANK_CONNECTION_DISABLED', 'tenant_payment_connections', (int)$id);
        header('Location: /settings/banking?disconnected=1');
        exit;
    }
}
