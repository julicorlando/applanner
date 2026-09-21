<?php
namespace App\Services;

use App\Core\Database;

final class ArenaDynamicPricingService
{
    private static array $settingsCache = [];
    private static array $occupancyCache = [];

    public function apply(
        int $tenantId,
        int $courtId,
        int $modalityId,
        \DateTimeImmutable $start,
        int $durationMinutes,
        float $baseHour,
        float $baseTotal
    ): array {
        $settings = $this->settings($tenantId);
        $baseHour = round(max(0, $baseHour), 2);
        $baseTotal = round(max(0, $baseTotal), 2);
        $result = [
            'enabled' => !empty($settings['dynamic_pricing_enabled']),
            'base_price_per_hour' => $baseHour,
            'base_total' => $baseTotal,
            'price_per_hour' => $baseHour,
            'total' => $baseTotal,
            'multiplier' => 1.0,
            'adjustments' => [],
            'occupancy_percent' => null,
        ];
        if (empty($settings['dynamic_pricing_enabled']) || $baseTotal <= 0 || $durationMinutes <= 0) {
            return $result;
        }

        $now = new \DateTimeImmutable();
        $leadSeconds = $start->getTimestamp() - $now->getTimestamp();
        $leadHours = $leadSeconds / 3600;
        $multiplier = 1.0;
        $adjustments = [];

        $lastMinuteHours = max(0, (int)($settings['dynamic_last_minute_hours'] ?? 4));
        $lastMinuteDiscount = $this->percent($settings['dynamic_last_minute_discount_percent'] ?? 10);
        if ($leadHours >= 0 && $lastMinuteHours > 0 && $leadHours <= $lastMinuteHours && $lastMinuteDiscount > 0) {
            $factor = 1 - ($lastMinuteDiscount / 100);
            $multiplier *= $factor;
            $adjustments[] = ['key' => 'last_minute', 'label' => 'Desconto de última hora', 'percent' => -$lastMinuteDiscount];
        }

        $occupancy = $this->occupancy($tenantId, $courtId, $start->format('Y-m-d'));
        $result['occupancy_percent'] = $occupancy;
        $highThreshold = $this->bounded((float)($settings['dynamic_high_occupancy_threshold'] ?? 70), 0, 100);
        $highSurcharge = $this->percent($settings['dynamic_high_occupancy_surcharge_percent'] ?? 10);
        $lowThreshold = $this->bounded((float)($settings['dynamic_low_occupancy_threshold'] ?? 30), 0, 100);
        $lowDiscount = $this->percent($settings['dynamic_low_occupancy_discount_percent'] ?? 5);
        $lowWindow = max(0, (int)($settings['dynamic_low_demand_window_hours'] ?? 24));

        if ($occupancy >= $highThreshold && $highSurcharge > 0) {
            $multiplier *= 1 + ($highSurcharge / 100);
            $adjustments[] = ['key' => 'high_occupancy', 'label' => 'Alta procura', 'percent' => $highSurcharge];
        } elseif ($leadHours >= 0 && $leadHours <= $lowWindow && $occupancy <= $lowThreshold && $lowDiscount > 0) {
            $multiplier *= 1 - ($lowDiscount / 100);
            $adjustments[] = ['key' => 'low_occupancy', 'label' => 'Horário com baixa procura', 'percent' => -$lowDiscount];
        }

        $weekendSurcharge = $this->percent($settings['dynamic_weekend_surcharge_percent'] ?? 0);
        if ((int)$start->format('N') >= 6 && $weekendSurcharge > 0) {
            $multiplier *= 1 + ($weekendSurcharge / 100);
            $adjustments[] = ['key' => 'weekend', 'label' => 'Ajuste de fim de semana', 'percent' => $weekendSurcharge];
        }

        $min = $this->bounded((float)($settings['dynamic_min_multiplier'] ?? 0.8), 0.1, 10);
        $max = $this->bounded((float)($settings['dynamic_max_multiplier'] ?? 1.3), $min, 10);
        $multiplier = max($min, min($max, $multiplier));
        $step = max(0.01, min(1000, (float)($settings['dynamic_rounding_step'] ?? 0.01)));
        $total = $this->roundStep($baseTotal * $multiplier, $step);
        $effectiveMultiplier = $baseTotal > 0 ? $total / $baseTotal : 1.0;
        $hour = round($total * 60 / max(1, $durationMinutes), 2);

        $result['price_per_hour'] = $hour;
        $result['total'] = round($total, 2);
        $result['multiplier'] = round($effectiveMultiplier, 4);
        $result['adjustments'] = $adjustments;
        return $result;
    }

    private function settings(int $tenantId): array
    {
        if (isset(self::$settingsCache[$tenantId])) return self::$settingsCache[$tenantId];
        $q = Database::connection()->prepare('SELECT * FROM sports_arena_settings WHERE tenant_id=:tenant');
        $q->execute(['tenant' => $tenantId]);
        return self::$settingsCache[$tenantId] = ($q->fetch() ?: []);
    }

    private function occupancy(int $tenantId, int $courtId, string $date): float
    {
        $key = $tenantId . '|' . $courtId . '|' . $date;
        if (isset(self::$occupancyCache[$key])) return self::$occupancyCache[$key];
        $pdo = Database::connection();
        $day = new \DateTimeImmutable($date . ' 00:00:00');
        $weekday = (int)$day->format('N');
        $hours = $pdo->prepare('SELECT start_time,end_time FROM sports_court_hours WHERE tenant_id=:tenant AND court_id=:court AND weekday=:weekday AND active=1');
        $hours->execute(['tenant' => $tenantId, 'court' => $courtId, 'weekday' => $weekday]);
        $availableMinutes = 0;
        foreach ($hours->fetchAll() ?: [] as $row) {
            $a = strtotime($date . ' ' . $row['start_time']);
            $b = strtotime($date . ' ' . $row['end_time']);
            if ($a !== false && $b !== false && $b > $a) $availableMinutes += (int)(($b - $a) / 60);
        }
        if ($availableMinutes <= 0) return self::$occupancyCache[$key] = 0.0;
        $q = $pdo->prepare(
            "SELECT starts_at,ends_at FROM sports_reservations WHERE tenant_id=:tenant AND court_id=:court
             AND status IN('pending_payment','confirmed','completed','no_show') AND starts_at<:end AND ends_at>:start"
        );
        $q->execute(['tenant' => $tenantId, 'court' => $courtId, 'start' => $date . ' 00:00:00', 'end' => $day->modify('+1 day')->format('Y-m-d H:i:s')]);
        $reserved = 0;
        foreach ($q->fetchAll() ?: [] as $row) {
            $a = max(strtotime($date . ' 00:00:00'), strtotime((string)$row['starts_at']));
            $b = min(strtotime($day->modify('+1 day')->format('Y-m-d H:i:s')), strtotime((string)$row['ends_at']));
            if ($a !== false && $b !== false && $b > $a) $reserved += (int)(($b - $a) / 60);
        }
        return self::$occupancyCache[$key] = round(min(100, max(0, $reserved * 100 / $availableMinutes)), 2);
    }

    private function percent(mixed $value): float { return $this->bounded((float)$value, 0, 100); }
    private function bounded(float $value, float $min, float $max): float { return max($min, min($max, $value)); }
    private function roundStep(float $value, float $step): float
    {
        if ($step <= 0.01) return round($value, 2);
        return round(round($value / $step) * $step, 2);
    }
}
