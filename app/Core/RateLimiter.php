<?php
namespace App\Core;

final class RateLimiter
{
    public static function hit(string $key, int $maxAttempts = 8, int $windowSeconds = 900): bool
    {
        $safe = hash('sha256', $key);
        $directory = __DIR__ . '/../../storage/rate_limits';
        if (!is_dir($directory) && !mkdir($directory, 0750, true) && !is_dir($directory)) {
            return false;
        }
        $file = $directory . '/' . $safe . '.json';
        $now = time();
        $data = ['start' => $now, 'count' => 0];

        if (is_file($file)) {
            $decoded = json_decode((string)file_get_contents($file), true);
            if (is_array($decoded)) {
                $data = $decoded;
            }
        }

        if (($data['start'] ?? 0) + $windowSeconds < $now) {
            $data = ['start' => $now, 'count' => 0];
        }

        $data['count'] = (int)($data['count'] ?? 0) + 1;
        if (file_put_contents($file, json_encode($data), LOCK_EX) === false) return false;

        return $data['count'] <= $maxAttempts;
    }

    public static function clear(string $key): void
    {
        $file = __DIR__ . '/../../storage/rate_limits/' . hash('sha256', $key) . '.json';
        if (is_file($file)) {
            @unlink($file);
        }
    }
}
