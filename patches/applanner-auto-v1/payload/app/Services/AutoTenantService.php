<?php
namespace App\Services;

use App\Core\Database;

final class AutoTenantService
{
    public static function isAutoCategory(?string $category): bool
    {
        $c=mb_strtolower(trim((string)$category));
        return in_array($c,['lava_jato','lava-jato','lava jato','detailing','estetica automotiva','estética automotiva','automotivo','automotive','auto'],true);
    }

    public static function isAutoTenant(int $tenantId): bool
    {
        $q=Database::connection()->prepare('SELECT category FROM tenants WHERE id=:t');
        $q->execute(['t'=>$tenantId]);
        return self::isAutoCategory((string)$q->fetchColumn());
    }
}
