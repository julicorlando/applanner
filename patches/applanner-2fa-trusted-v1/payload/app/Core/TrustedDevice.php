<?php
namespace App\Core;

final class TrustedDevice
{
    private const COOKIE_PREFIX = 'applanner_2fa_trusted_';
    private const DEFAULT_DAYS = 30;

    public static function trustDays(): int
    {
        $days = (int)(getenv('TWO_FACTOR_TRUST_DAYS') ?: self::DEFAULT_DAYS);
        return max(1, min(90, $days));
    }

    public static function isTrusted(int $userId, int $sessionVersion): bool
    {
        $parts = self::cookieParts($userId);
        if (!$parts) return false;
        [$selector, $validator] = $parts;

        try {
            $pdo = Database::connection();
            $stmt = $pdo->prepare(
                'SELECT id,validator_hash,session_version FROM two_factor_trusted_devices
                 WHERE selector=:selector AND user_id=:uid AND revoked_at IS NULL AND expires_at>NOW() LIMIT 1'
            );
            $stmt->execute(['selector'=>$selector,'uid'=>$userId]);
            $row = $stmt->fetch();
            if (!$row) {
                self::clearCookie($userId);
                return false;
            }

            if ((int)$row['session_version'] !== $sessionVersion) {
                $pdo->prepare('UPDATE two_factor_trusted_devices SET revoked_at=COALESCE(revoked_at,NOW()) WHERE id=:id')->execute(['id'=>$row['id']]);
                self::clearCookie($userId);
                return false;
            }

            $expected = (string)$row['validator_hash'];
            $actual = hash('sha256', $validator);
            if (!hash_equals($expected, $actual)) {
                $pdo->prepare('UPDATE two_factor_trusted_devices SET revoked_at=COALESCE(revoked_at,NOW()) WHERE id=:id')->execute(['id'=>$row['id']]);
                self::clearCookie($userId);
                SecurityLogger::log('2fa.trusted_device_token_mismatch',['user_id'=>$userId]);
                return false;
            }

            $pdo->prepare('UPDATE two_factor_trusted_devices SET last_used_at=NOW(),ip_address=:ip WHERE id=:id')->execute([
                'ip'=>substr((string)($_SERVER['REMOTE_ADDR']??''),0,64) ?: null,
                'id'=>$row['id'],
            ]);
            SecurityLogger::log('2fa.trusted_device_used',['user_id'=>$userId,'device_id'=>(int)$row['id']]);
            return true;
        } catch (\Throwable $e) {
            SecurityLogger::log('2fa.trusted_device_check_failed',['user_id'=>$userId,'error'=>get_class($e)]);
            return false;
        }
    }

    public static function trust(int $userId, int $sessionVersion): void
    {
        $selector = bin2hex(random_bytes(12));
        $validator = bin2hex(random_bytes(32));
        $expiresTs = time() + (self::trustDays() * 86400);
        $ua = substr((string)($_SERVER['HTTP_USER_AGENT']??''),0,500);
        $ip = substr((string)($_SERVER['REMOTE_ADDR']??''),0,64);
        $pdo = Database::connection();

        $pdo->prepare('DELETE FROM two_factor_trusted_devices WHERE expires_at<=NOW() OR revoked_at IS NOT NULL')->execute();

        $current = self::cookieParts($userId);
        if ($current) {
            $pdo->prepare('UPDATE two_factor_trusted_devices SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=:uid AND selector=:selector')
                ->execute(['uid'=>$userId,'selector'=>$current[0]]);
        }

        $stmt = $pdo->prepare(
            'INSERT INTO two_factor_trusted_devices
             (user_id,selector,validator_hash,session_version,device_label,user_agent,ip_address,last_used_at,expires_at,created_at)
             VALUES(:uid,:selector,:hash,:sv,:label,:ua,:ip,NOW(),:expires,NOW())'
        );
        $stmt->execute([
            'uid'=>$userId,
            'selector'=>$selector,
            'hash'=>hash('sha256',$validator),
            'sv'=>$sessionVersion,
            'label'=>self::deviceLabel($ua),
            'ua'=>$ua ?: null,
            'ip'=>$ip ?: null,
            'expires'=>date('Y-m-d H:i:s',$expiresTs),
        ]);

        self::setCookie($userId,$selector.'.'.$validator,$expiresTs);
        SecurityLogger::log('2fa.trusted_device_created',['user_id'=>$userId,'days'=>self::trustDays()]);
        Audit::log('auth.2fa_trusted_device_created','users',$userId,null,['expires_at'=>date('c',$expiresTs)]);
    }

    public static function listForUser(int $userId): array
    {
        try {
            $stmt = Database::connection()->prepare(
                'SELECT id,selector,device_label,user_agent,ip_address,last_used_at,expires_at,created_at
                 FROM two_factor_trusted_devices
                 WHERE user_id=:uid AND revoked_at IS NULL AND expires_at>NOW()
                 ORDER BY COALESCE(last_used_at,created_at) DESC'
            );
            $stmt->execute(['uid'=>$userId]);
            $rows = $stmt->fetchAll() ?: [];
            $current = self::cookieParts($userId);
            $currentSelector = $current[0] ?? null;
            foreach ($rows as &$row) $row['is_current'] = $currentSelector && hash_equals((string)$row['selector'],$currentSelector);
            unset($row);
            return $rows;
        } catch (\Throwable) {
            return [];
        }
    }

    public static function revoke(int $userId, int $deviceId): bool
    {
        $pdo = Database::connection();
        $q = $pdo->prepare('SELECT selector FROM two_factor_trusted_devices WHERE id=:id AND user_id=:uid LIMIT 1');
        $q->execute(['id'=>$deviceId,'uid'=>$userId]);
        $selector = $q->fetchColumn();
        if (!$selector) return false;
        $pdo->prepare('UPDATE two_factor_trusted_devices SET revoked_at=COALESCE(revoked_at,NOW()) WHERE id=:id AND user_id=:uid')->execute(['id'=>$deviceId,'uid'=>$userId]);
        $current = self::cookieParts($userId);
        if ($current && hash_equals((string)$selector,(string)$current[0])) self::clearCookie($userId);
        Audit::log('auth.2fa_trusted_device_revoked','users',$userId,null,['device_id'=>$deviceId]);
        return true;
    }

    public static function revokeAllForUser(int $userId): void
    {
        $currentBelongs = false;
        $current = self::cookieParts($userId);
        if ($current) {
            try {
                $q = Database::connection()->prepare('SELECT COUNT(*) FROM two_factor_trusted_devices WHERE user_id=:uid AND selector=:selector');
                $q->execute(['uid'=>$userId,'selector'=>$current[0]]);
                $currentBelongs = (bool)$q->fetchColumn();
            } catch (\Throwable) {}
        }
        Database::connection()->prepare('UPDATE two_factor_trusted_devices SET revoked_at=COALESCE(revoked_at,NOW()) WHERE user_id=:uid AND revoked_at IS NULL')->execute(['uid'=>$userId]);
        if ($currentBelongs) self::clearCookie($userId);
    }

    private static function clearCookie(int $userId): void
    {
        $name=self::cookieName($userId);
        self::setCookie($userId,'', time()-3600);
        unset($_COOKIE[$name]);
    }

    private static function cookieParts(int $userId): ?array
    {
        $name=self::cookieName($userId);
        $raw = (string)($_COOKIE[$name] ?? '');
        if ($raw === '' || !str_contains($raw,'.')) return null;
        [$selector,$validator] = explode('.',$raw,2);
        if (!preg_match('/^[a-f0-9]{24}$/',$selector) || !preg_match('/^[a-f0-9]{64}$/',$validator)) {
            self::clearCookie($userId);
            return null;
        }
        return [$selector,$validator];
    }

    private static function setCookie(int $userId, string $value, int $expires): void
    {
        $secure = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
            || strtolower((string)($_SERVER['HTTP_X_FORWARDED_PROTO']??'')) === 'https';
        setcookie(self::cookieName($userId),$value,[
            'expires'=>$expires,
            'path'=>'/',
            'secure'=>$secure,
            'httponly'=>true,
            'samesite'=>'Lax',
        ]);
        if ($value !== '') $_COOKIE[self::cookieName($userId)] = $value;
    }

    private static function cookieName(int $userId): string
    {
        return self::COOKIE_PREFIX.$userId;
    }

    private static function deviceLabel(string $ua): string
    {
        $browser = 'Navegador';
        if (stripos($ua,'Edg/')!==false) $browser='Microsoft Edge';
        elseif (stripos($ua,'Firefox/')!==false) $browser='Firefox';
        elseif (stripos($ua,'Chrome/')!==false) $browser='Chrome';
        elseif (stripos($ua,'Safari/')!==false) $browser='Safari';

        $os = 'dispositivo';
        if (stripos($ua,'Windows')!==false) $os='Windows';
        elseif (stripos($ua,'iPhone')!==false) $os='iPhone';
        elseif (stripos($ua,'iPad')!==false) $os='iPad';
        elseif (stripos($ua,'Android')!==false) $os='Android';
        elseif (stripos($ua,'Macintosh')!==false) $os='macOS';
        elseif (stripos($ua,'Linux')!==false) $os='Linux';
        return $browser.' em '.$os;
    }
}
