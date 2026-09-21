<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require dirname(__DIR__) . '/app/Core/bootstrap.php';

use App\Core\Database;
use App\Services\ArenaMaintenanceService;

$pdo = Database::connection();
$tenants = $pdo->query(
    "SELECT DISTINCT t.id FROM tenants t
     JOIN subscriptions s ON s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=t.id)
     JOIN modules m ON m.slug='sports_courts' AND m.active=1
     LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id
     LEFT JOIN tenant_modules tm ON tm.tenant_id=t.id AND tm.module_id=m.id
     WHERE t.status IN('trial','active') AND t.deleted_at IS NULL AND COALESCE(tm.enabled,pm.enabled,0)=1"
)->fetchAll(PDO::FETCH_COLUMN);
$service = new ArenaMaintenanceService();
$summary = ['tenants'=>0,'expired'=>0,'membership_generated'=>0,'membership_conflicts'=>0,'waitlist_offers'=>0];
foreach ($tenants as $tenantId) {
    try {
        $result = $service->runTenant((int)$tenantId); $summary['tenants']++;
        foreach (['expired','membership_generated','membership_conflicts','waitlist_offers'] as $key) $summary[$key] += (int)($result[$key] ?? 0);
    } catch (Throwable $e) {
        error_log('[ApPlanner Arena Cron] tenant=' . (int)$tenantId . ' ' . $e->getMessage());
    }
}
echo 'Arena: ' . json_encode($summary, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . PHP_EOL;
