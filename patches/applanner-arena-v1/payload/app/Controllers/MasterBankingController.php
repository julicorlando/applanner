<?php
namespace App\Controllers;

use App\Core\{Auth, Database, View};

final class MasterBankingController
{
    public function index(): void
    {
        Auth::requireRole('master');
        $pdo = Database::connection();
        $connections = $pdo->query(
            "SELECT c.id,c.tenant_id,t.name tenant_name,c.provider,c.display_name,c.environment,c.status,c.last_tested_at,c.last_sync_at,c.last_error_code,c.created_at,
                    (SELECT COUNT(*) FROM tenant_payment_transactions tx WHERE tx.connection_id=c.id) transaction_count,
                    (SELECT COALESCE(SUM(tx.net_amount),0) FROM tenant_payment_transactions tx WHERE tx.connection_id=c.id AND tx.status='paid') paid_total
             FROM tenant_payment_connections c
             JOIN tenants t ON t.id=c.tenant_id
             ORDER BY c.updated_at DESC,c.id DESC"
        )->fetchAll() ?: [];
        View::render('master/banking-integrations', [
            'title' => 'Integrações Bancárias',
            'connections' => $connections,
        ]);
    }
}
