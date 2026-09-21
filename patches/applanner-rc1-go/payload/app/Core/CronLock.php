<?php
namespace App\Core;

/**
 * Bloqueio simples para impedir sobreposição do mesmo cron.
 * O lock é liberado automaticamente quando o processo termina.
 */
final class CronLock
{
    /** @var array<string, resource> */
    private static array $handles = [];

    public static function acquire(string $name): bool
    {
        $safe = preg_replace('/[^a-z0-9_-]+/i', '-', $name) ?: 'cron';
        $dir = dirname(__DIR__, 2) . '/storage/cache';
        if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
            throw new \RuntimeException('Não foi possível criar a pasta de locks dos crons.');
        }

        $path = $dir . '/cron-' . $safe . '.lock';
        $handle = @fopen($path, 'c+');
        if (!$handle) {
            throw new \RuntimeException('Não foi possível abrir o arquivo de lock do cron.');
        }

        if (!@flock($handle, LOCK_EX | LOCK_NB)) {
            @fclose($handle);
            return false;
        }

        @ftruncate($handle, 0);
        @fwrite($handle, (string)getmypid() . ' ' . date('c'));
        @fflush($handle);
        self::$handles[$safe] = $handle;
        return true;
    }
}
