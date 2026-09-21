<?php
namespace App\Services;

use App\Core\Database;

final class SportsAvailabilityService
{
    public function nextAvailableDate(int $tenant, int $court, int $modality, string $from, int $duration, int $days = 30): ?string
    {
        $date = \DateTimeImmutable::createFromFormat('!Y-m-d', $from);
        if (!$date) return null;
        for ($i = 1; $i <= $days; $i++) {
            $candidate = $date->modify('+' . $i . ' days')->format('Y-m-d');
            if ($this->slots($tenant, $court, $modality, $candidate, $duration)) return $candidate;
        }
        return null;
    }

    public function slots(int $tenant, int $court, int $modality, string $date, int $duration, ?int $excludeReservationId = null): array
    {
        $pdo = Database::connection();
        $day = \DateTimeImmutable::createFromFormat('!Y-m-d', $date);
        if (!$day) return [];
        $weekday = (int)$day->format('N');

        $q = $pdo->prepare('SELECT * FROM sports_courts WHERE id=:c AND tenant_id=:t AND active=1');
        $q->execute(['c' => $court, 't' => $tenant]);
        $courtRow = $q->fetch();
        if (!$courtRow) return [];
        $duration = max((int)$courtRow['minimum_minutes'], min((int)$courtRow['maximum_minutes'], $duration));

        $q = $pdo->prepare(
            'SELECT 1 FROM sports_court_modalities cm JOIN sports_modalities m ON m.id=cm.modality_id
             WHERE cm.court_id=:c AND cm.modality_id=:m AND m.tenant_id=:t AND m.active=1'
        );
        $q->execute(['c' => $court, 'm' => $modality, 't' => $tenant]);
        if (!$q->fetchColumn()) return [];

        $q = $pdo->prepare('SELECT start_time,end_time FROM sports_court_hours WHERE court_id=:c AND tenant_id=:t AND weekday=:d AND active=1 ORDER BY start_time');
        $q->execute(['c' => $court, 't' => $tenant, 'd' => $weekday]);
        $hours = $q->fetchAll() ?: [];

        $settings = $pdo->prepare('SELECT default_slot_minutes,minimum_notice_minutes,maximum_days_ahead FROM sports_settings WHERE tenant_id=:t');
        $settings->execute(['t' => $tenant]);
        $cfg = $settings->fetch() ?: ['default_slot_minutes' => 60, 'minimum_notice_minutes' => 60, 'maximum_days_ahead' => 90];

        $now = new \DateTimeImmutable();
        if ($day < $now->setTime(0, 0) || $day > $now->modify('+' . (int)$cfg['maximum_days_ahead'] . ' days')->setTime(23, 59)) return [];
        $step = max(5, (int)$cfg['default_slot_minutes']);
        $out = [];

        foreach ($hours as $hoursRow) {
            $cursor = new \DateTimeImmutable($date . ' ' . $hoursRow['start_time']);
            $limit = new \DateTimeImmutable($date . ' ' . $hoursRow['end_time']);
            while ($cursor->modify('+' . $duration . ' minutes') <= $limit) {
                $end = $cursor->modify('+' . $duration . ' minutes');
                if (
                    $cursor >= $now->modify('+' . (int)$cfg['minimum_notice_minutes'] . ' minutes')
                    && $this->free($tenant, $court, $cursor, $end, (int)$courtRow['interval_minutes'], $excludeReservationId)
                ) {
                    $quote = $this->quote($tenant, $court, $modality, $cursor, $duration);
                    if ($quote !== null) {
                        $out[] = [
                            'value' => $cursor->format('Y-m-d H:i:s'),
                            'label' => $cursor->format('H:i'),
                            'ends_at' => $end->format('Y-m-d H:i:s'),
                            'total' => $quote['total'],
                            'formatted' => 'R$ ' . number_format($quote['total'], 2, ',', '.'),
                            'price_per_hour' => $quote['price_per_hour'],
                        ];
                    }
                }
                $cursor = $cursor->modify('+' . $step . ' minutes');
            }
        }
        return $out;
    }

    public function quote(int $tenant, int $court, int $modality, \DateTimeImmutable $start, int $duration): ?array
    {
        $q = Database::connection()->prepare(
            "SELECT pr.price_per_hour
             FROM sports_price_rules pr
             LEFT JOIN sports_price_rule_extensions x ON x.price_rule_id=pr.id AND x.tenant_id=pr.tenant_id
             WHERE pr.tenant_id=:t AND pr.court_id=:c AND pr.active=1
               AND (pr.modality_id IS NULL OR pr.modality_id=:m)
               AND (pr.weekday IS NULL OR pr.weekday=:d)
               AND (pr.start_time IS NULL OR pr.start_time<=:time1)
               AND (pr.end_time IS NULL OR pr.end_time>:time2)
               AND (x.specific_date IS NULL OR x.specific_date=:date1)
               AND (x.valid_from IS NULL OR x.valid_from<=:date2)
               AND (x.valid_to IS NULL OR x.valid_to>=:date3)
               AND (x.minimum_duration_minutes IS NULL OR x.minimum_duration_minutes<=:duration1)
               AND (x.maximum_duration_minutes IS NULL OR x.maximum_duration_minutes>=:duration2)
             ORDER BY (x.specific_date IS NOT NULL) DESC,
                      (x.rule_type='holiday') DESC,(x.rule_type='special') DESC,
                      (x.minimum_duration_minutes IS NOT NULL OR x.maximum_duration_minutes IS NOT NULL) DESC,
                      (pr.modality_id IS NOT NULL) DESC,(pr.weekday IS NOT NULL) DESC,
                      (pr.start_time IS NOT NULL) DESC,pr.priority DESC,pr.id DESC LIMIT 1"
        );
        $q->execute([
            't' => $tenant, 'c' => $court, 'm' => $modality, 'd' => (int)$start->format('N'),
            'time1' => $start->format('H:i:s'), 'time2' => $start->format('H:i:s'),
            'date1' => $start->format('Y-m-d'), 'date2' => $start->format('Y-m-d'), 'date3' => $start->format('Y-m-d'),
            'duration1' => $duration, 'duration2' => $duration,
        ]);
        $price = $q->fetchColumn();
        if ($price === false) return null;
        $hour = round((float)$price, 2);
        return ['price_per_hour' => $hour, 'total' => round($hour * $duration / 60, 2)];
    }

    public function free(
        int $tenant,
        int $court,
        \DateTimeImmutable $start,
        \DateTimeImmutable $end,
        int $buffer = 0,
        ?int $excludeReservationId = null
    ): bool {
        $from = $start->modify('-' . $buffer . ' minutes')->format('Y-m-d H:i:s');
        $to = $end->modify('+' . $buffer . ' minutes')->format('Y-m-d H:i:s');
        $pdo = Database::connection();

        $sql = "SELECT 1 FROM sports_reservations
                WHERE tenant_id=:t AND court_id=:c AND status IN('pending_payment','confirmed')
                  AND starts_at<:ends AND ends_at>:starts";
        $params = ['t' => $tenant, 'c' => $court, 'ends' => $to, 'starts' => $from];
        if ($excludeReservationId !== null && $excludeReservationId > 0) {
            $sql .= ' AND id<>:exclude';
            $params['exclude'] = $excludeReservationId;
        }
        $sql .= ' LIMIT 1';
        $q = $pdo->prepare($sql);
        $q->execute($params);
        if ($q->fetchColumn()) return false;

        $q = $pdo->prepare(
            "SELECT 1 FROM sports_court_blocks
             WHERE tenant_id=:t AND court_id=:c AND status='active' AND starts_at<:ends AND ends_at>:starts LIMIT 1"
        );
        $q->execute(['t' => $tenant, 'c' => $court, 'ends' => $to, 'starts' => $from]);
        return !$q->fetchColumn();
    }
}
