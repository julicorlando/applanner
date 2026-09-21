<?php
namespace App\Services;

use App\Core\Database;

final class ArenaTenantService
{
    private const CATEGORIES = [
        'centro_esportivo', 'centro esportivo', 'esportes', 'quadras', 'arena',
        'arena esportiva', 'arena / centro esportivo', 'centro de esportes', 'esportivo'
    ];

    public static function isArena(int $tenantId): bool
    {
        // Em tenant existente, o módulo habilitado é a fonte de verdade. A categoria
        // continua útil apenas para telas de cadastro/preview que ainda não possuem assinatura.
        return $tenantId > 0 && ModuleService::has('sports_courts', $tenantId);
    }

    public static function isArenaCategory(?string $category): bool
    {
        return in_array(self::normalize((string)$category), self::CATEGORIES, true);
    }

    public static function publicPath(array $tenant, ?int $tenantId = null): string
    {
        $tenantId ??= (int)($tenant['id'] ?? 0);
        $arena = $tenantId > 0 ? self::isArena($tenantId) : self::isArenaCategory((string)($tenant['category'] ?? ''));
        if ($arena) {
            $slug = trim((string)($tenant['public_slug'] ?? '')) ?: trim((string)($tenant['public_short_code'] ?? ''));
            return '/arena/' . rawurlencode($slug);
        }
        $slug = trim((string)($tenant['public_short_code'] ?? '')) ?: trim((string)($tenant['public_slug'] ?? ''));
        return '/a/' . rawurlencode($slug);
    }

    private static function normalize(string $value): string
    {
        $value = mb_strtolower(trim($value));
        $value = str_replace(['á','à','ã','â','ä','é','è','ê','ë','í','ì','î','ï','ó','ò','õ','ô','ö','ú','ù','û','ü','ç'], ['a','a','a','a','a','e','e','e','e','i','i','i','i','o','o','o','o','o','u','u','u','u','c'], $value);
        $value = preg_replace('/\s+/u', ' ', $value) ?: $value;
        return $value;
    }
}
