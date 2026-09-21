<?php
namespace App\Services;

use App\Core\{Database,TenantContext,HttpException};

final class ModuleService
{
    public static function has(string $module, ?int $tenantId=null): bool
    {
        $tenantId ??= TenantContext::id();
        $sql="SELECT COALESCE(tm.enabled,pm.enabled,0)
              FROM subscriptions s
              JOIN modules m ON m.slug=:module AND m.active=1
              LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id
              LEFT JOIN tenant_modules tm ON tm.tenant_id=s.tenant_id AND tm.module_id=m.id
              WHERE s.tenant_id=:tenant
                AND s.status IN('trial','active','past_due','suspended')
              ORDER BY s.id DESC LIMIT 1";
        $q=Database::connection()->prepare($sql);
        $q->execute(['module'=>$module,'tenant'=>$tenantId]);
        return (bool)$q->fetchColumn();
    }

    public static function enabledForTenant(?int $tenantId=null): array
    {
        $tenantId ??= TenantContext::id();
        $q=Database::connection()->prepare(
            "SELECT m.slug,COALESCE(tm.enabled,pm.enabled,0) enabled
             FROM modules m
             LEFT JOIN subscriptions s ON s.tenant_id=:tenant AND s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=:tenant2)
             LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id
             LEFT JOIN tenant_modules tm ON tm.tenant_id=:tenant3 AND tm.module_id=m.id
             WHERE m.active=1"
        );
        $q->execute(['tenant'=>$tenantId,'tenant2'=>$tenantId,'tenant3'=>$tenantId]);
        $result=[];
        foreach($q->fetchAll() as $row)$result[$row['slug']]=(bool)$row['enabled'];
        return $result;
    }

    public static function limit(string $key, ?int $tenantId=null, ?int $default=null): ?int
    {
        $tenantId ??= TenantContext::id();
        $q=Database::connection()->prepare(
            "SELECT p.features_json
             FROM subscriptions s JOIN plans p ON p.id=s.plan_id
             WHERE s.tenant_id=:tenant ORDER BY s.id DESC LIMIT 1"
        );
        $q->execute(['tenant'=>$tenantId]);
        $json=$q->fetchColumn();
        if(!$json)return $default;
        $features=json_decode((string)$json,true);
        if(!is_array($features)||!array_key_exists($key,$features))return $default;
        $value=filter_var($features[$key],FILTER_VALIDATE_INT);
        return $value===false?$default:(int)$value;
    }

    public static function require(string $module): void
    {
        if(!self::has($module))HttpException::abort(403,'Este recurso não está incluído no seu plano.');
    }
}
