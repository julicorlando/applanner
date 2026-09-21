<?php
namespace App\Core;

final class SecurityLogger
{
    public static function log(string $event, array $context = []): void
    {
        foreach (array_keys($context) as $key) {
            if (preg_match('/password|token|secret|authorization/i', (string)$key)) unset($context[$key]);
        }
        $record = ['at'=>date('c'),'event'=>$event,'user_id'=>Auth::user()['id'] ?? null,'tenant_id'=>Auth::user()['tenant_id'] ?? null,'ip'=>$_SERVER['REMOTE_ADDR'] ?? null,'context'=>$context];
        @file_put_contents(__DIR__ . '/../../storage/logs/security.log', json_encode($record, JSON_UNESCAPED_UNICODE) . "\n", FILE_APPEND | LOCK_EX);
    }
}
