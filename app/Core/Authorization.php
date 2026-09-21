<?php
namespace App\Core;

final class Authorization
{
    public static function allows(string $permission): bool
    {
        $user = Auth::user();
        if (!$user) return false;
        if (($user['role'] ?? '') === 'master') return str_starts_with($permission, 'master.');
        if(Auth::commercialSupportEnabled()&&in_array($permission,['master.support.manage','master.support.impersonate'],true))return true;
        return in_array($permission, $user['permissions'] ?? [], true);
    }

    public static function require(string $permission): void
    {
        Auth::requireLogin();
        if (!self::allows($permission)) {
            SecurityLogger::log('authorization.denied', ['permission'=>$permission]);
            HttpException::abort(403, 'Você não possui permissão para esta ação.');
        }
    }
}
