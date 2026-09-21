<?php
namespace App\Core;

final class TenantContext
{
    public static function id(): int
    {
        Auth::requireLogin();
        $tenantId = Auth::user()['tenant_id'] ?? null;
        if (!is_int($tenantId) || $tenantId <= 0) {
            SecurityLogger::log('tenant.missing');
            HttpException::abort(403, 'Esta área exige uma empresa ativa.');
        }
        return $tenantId;
    }
}
