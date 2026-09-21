<?php
namespace App\Services;

use App\Core\Database;

final class BehaviorEngine
{
    public function recalculateCustomer(int $tenantId, int $customerId): array
    {
        $pdo = Database::connection();

        $owner = $pdo->prepare("SELECT 1 FROM customers WHERE id=:customer_id AND tenant_id=:tenant_id");
        $owner->execute(['customer_id'=>$customerId,'tenant_id'=>$tenantId]);
        if (!$owner->fetchColumn()) throw new \RuntimeException('Cliente não encontrado nesta empresa.');

        $stmt = $pdo->prepare(
            "SELECT a.starts_at, a.service_id, a.professional_id
             FROM appointments a
             WHERE a.tenant_id = :tenant_id
               AND a.customer_id = :customer_id
               AND a.status = 'completed'
             ORDER BY a.starts_at ASC"
        );
        $stmt->execute(['tenant_id' => $tenantId, 'customer_id' => $customerId]);
        $rows = $stmt->fetchAll();

        $intervals = [];
        for ($i = 1; $i < count($rows); $i++) {
            $prev = new \DateTimeImmutable($rows[$i - 1]['starts_at']);
            $curr = new \DateTimeImmutable($rows[$i]['starts_at']);
            $days = (int)$prev->diff($curr)->format('%a');
            if ($days > 0 && $days <= 365) {
                $intervals[] = $days;
            }
        }

        $analysis = self::analyzeIntervals($intervals);
        $avg = $analysis['average'];
        $last = $rows ? end($rows)['starts_at'] : null;
        $next = null;
        $confidence = 0;

        if ($avg !== null && $last) {
            $nextDate = (new \DateTimeImmutable($last))->modify('+' . max(1, (int)round($avg)) . ' days');
            $next = $nextDate->format('Y-m-d');
            $confidence = $analysis['confidence'];
        }

        $payload = [
            'avg_interval_days' => $avg !== null ? round($avg, 2) : null,
            'median_interval_days' => $analysis['median'],
            'std_deviation_days' => $analysis['standard_deviation'],
            'last_visit_at' => $last,
            'next_expected_date' => $next,
            'confidence_score' => $confidence,
            'visits_count' => count($rows),
            'intervals_json' => json_encode($analysis['filtered_intervals']),
        ];

        $stmt = $pdo->prepare(
            "INSERT INTO behavior_profiles
             (tenant_id, customer_id, avg_interval_days, median_interval_days, std_deviation_days, last_visit_at, next_expected_date, confidence_score, visits_count, intervals_json, updated_at)
             VALUES (:tenant_id, :customer_id, :avg_interval_days, :median_interval_days, :std_deviation_days, :last_visit_at, :next_expected_date, :confidence_score, :visits_count, :intervals_json, NOW())
             ON DUPLICATE KEY UPDATE
                avg_interval_days = VALUES(avg_interval_days),
                median_interval_days = VALUES(median_interval_days),
                std_deviation_days = VALUES(std_deviation_days),
                last_visit_at = VALUES(last_visit_at),
                next_expected_date = VALUES(next_expected_date),
                confidence_score = VALUES(confidence_score),
                visits_count = VALUES(visits_count),
                intervals_json = VALUES(intervals_json),
                updated_at = NOW()"
        );
        $stmt->execute(['tenant_id' => $tenantId, 'customer_id' => $customerId] + $payload);

        $serviceIds = array_values(array_unique(array_map(fn($r)=>(int)$r['service_id'], $rows)));
        foreach ($serviceIds as $serviceId) $this->recalculateService($tenantId, $customerId, $serviceId);

        return $payload;
    }

    public static function analyzeIntervals(array $intervals): array
    {
        $values = array_values(array_filter(array_map('intval', $intervals), fn($v)=>$v > 0 && $v <= 365));
        sort($values);
        if (!$values) return ['average'=>null,'median'=>null,'standard_deviation'=>null,'confidence'=>0,'filtered_intervals'=>[]];
        $median = self::median($values);
        $deviations = array_map(fn($v)=>abs($v-$median), $values);
        $mad = self::median($deviations);
        $filtered = $mad > 0 ? array_values(array_filter($values, fn($v)=>abs($v-$median) <= 3*$mad)) : $values;
        $recent = array_slice($filtered, -8);
        $average = array_sum($recent)/count($recent);
        $variance = array_sum(array_map(fn($v)=>(($v-$average)**2), $recent))/count($recent);
        $std = sqrt($variance);
        $historyScore = min(55, count($recent)*8);
        $consistency = $average > 0 ? max(0, 35-(int)round(($std/$average)*100)) : 0;
        return ['average'=>round($average,2),'median'=>round(self::median($recent),2),'standard_deviation'=>round($std,2),'confidence'=>min(95,$historyScore+$consistency),'filtered_intervals'=>$recent];
    }

    private static function median(array $values): float
    {
        sort($values); $count=count($values); $middle=intdiv($count,2);
        return $count%2 ? (float)$values[$middle] : ($values[$middle-1]+$values[$middle])/2;
    }

    private function recalculateService(int $tenantId, int $customerId, int $serviceId): void
    {
        $pdo=Database::connection();
        $stmt=$pdo->prepare("SELECT starts_at FROM appointments WHERE tenant_id=:tenant AND customer_id=:customer AND service_id=:service AND status='completed' ORDER BY starts_at");
        $stmt->execute(['tenant'=>$tenantId,'customer'=>$customerId,'service'=>$serviceId]); $dates=$stmt->fetchAll(\PDO::FETCH_COLUMN); $intervals=[];
        for($i=1;$i<count($dates);$i++){ $days=(int)(new \DateTimeImmutable($dates[$i-1]))->diff(new \DateTimeImmutable($dates[$i]))->format('%a'); if($days>0)$intervals[]=$days; }
        $a=self::analyzeIntervals($intervals); $last=$dates ? end($dates) : null; $next=($last && $a['average']) ? (new \DateTimeImmutable($last))->modify('+'.max(1,(int)round($a['average'])).' days')->format('Y-m-d') : null;
        $up=$pdo->prepare("INSERT INTO behavior_service_profiles (tenant_id,customer_id,service_id,avg_interval_days,median_interval_days,std_deviation_days,last_visit_at,next_expected_date,confidence_score,visits_count,intervals_json,updated_at) VALUES (:tenant,:customer,:service,:avg,:median,:std,:last,:next,:confidence,:visits,:intervals,NOW()) ON DUPLICATE KEY UPDATE avg_interval_days=VALUES(avg_interval_days),median_interval_days=VALUES(median_interval_days),std_deviation_days=VALUES(std_deviation_days),last_visit_at=VALUES(last_visit_at),next_expected_date=VALUES(next_expected_date),confidence_score=VALUES(confidence_score),visits_count=VALUES(visits_count),intervals_json=VALUES(intervals_json),updated_at=NOW()");
        $up->execute(['tenant'=>$tenantId,'customer'=>$customerId,'service'=>$serviceId,'avg'=>$a['average'],'median'=>$a['median'],'std'=>$a['standard_deviation'],'last'=>$last,'next'=>$next,'confidence'=>$a['confidence'],'visits'=>count($dates),'intervals'=>json_encode($a['filtered_intervals'])]);
    }

    public function opportunities(int $tenantId, int $daysAhead = 5): array
    {
        $pdo = Database::connection();
        $stmt = $pdo->prepare(
            "SELECT c.id, c.name, c.phone, c.email, c.consent_marketing,
                    bp.avg_interval_days, bp.median_interval_days, bp.last_visit_at,
                    bp.next_expected_date, bp.confidence_score, bp.visits_count,
                    a.service_price_snapshot, s.name AS last_service_name,
                    p.name AS last_professional_name,
                    DATEDIFF(CURDATE(),bp.next_expected_date) AS days_overdue,
                    CASE
                      WHEN bp.next_expected_date < CURDATE() THEN 'overdue'
                      ELSE 'due_soon'
                    END AS opportunity_type
             FROM behavior_profiles bp
             INNER JOIN customers c ON c.id = bp.customer_id AND c.tenant_id = bp.tenant_id
             LEFT JOIN appointments a ON a.id=(SELECT a2.id FROM appointments a2 WHERE a2.tenant_id=bp.tenant_id AND a2.customer_id=bp.customer_id AND a2.status='completed' ORDER BY a2.starts_at DESC,a2.id DESC LIMIT 1)
             LEFT JOIN services s ON s.id=a.service_id AND s.tenant_id=bp.tenant_id
             LEFT JOIN professionals p ON p.id=a.professional_id AND p.tenant_id=bp.tenant_id
             WHERE bp.tenant_id = :tenant_id
               AND bp.next_expected_date IS NOT NULL
               AND bp.next_expected_date <= DATE_ADD(CURDATE(), INTERVAL :days DAY)
               AND c.status = 'active'
               AND NOT EXISTS (
                   SELECT 1 FROM appointments a
                   WHERE a.tenant_id = bp.tenant_id
                     AND a.customer_id = bp.customer_id
                     AND a.status IN ('pending','confirmed')
                     AND a.starts_at >= NOW()
               )
             ORDER BY bp.next_expected_date ASC, bp.confidence_score DESC
             LIMIT 100"
        );
        $stmt->bindValue(':tenant_id', $tenantId, \PDO::PARAM_INT);
        $stmt->bindValue(':days', $daysAhead, \PDO::PARAM_INT);
        $stmt->execute();
        return $stmt->fetchAll();
    }
}
