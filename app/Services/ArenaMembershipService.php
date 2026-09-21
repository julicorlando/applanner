<?php
namespace App\Services;

use App\Core\Database;

final class ArenaMembershipService
{
    public function generate(int $tenantId, int $membershipId): array
    {
        $pdo = Database::connection();
        $q = $pdo->prepare(
            "SELECT sm.*,c.name customer_name,c.phone customer_phone,c.email customer_email
             FROM sports_memberships sm JOIN customers c ON c.id=sm.customer_id AND c.tenant_id=sm.tenant_id
             WHERE sm.id=:id AND sm.tenant_id=:tenant AND sm.status='active'"
        );
        $q->execute(['id' => $membershipId, 'tenant' => $tenantId]);
        $membership = $q->fetch();
        if (!$membership) throw new \DomainException('Mensalista ativo não encontrado.');

        $fromDate = max(date('Y-m-d'), (string)$membership['start_date']);
        if (!empty($membership['next_generation_date']) && $membership['next_generation_date'] > $fromDate) {
            $fromDate = (string)$membership['next_generation_date'];
        }
        $from = new \DateTimeImmutable($fromDate . ' 00:00:00');
        $to = (new \DateTimeImmutable('today'))->modify('+' . max(7, (int)$membership['generate_days_ahead']) . ' days');
        if (!empty($membership['end_date'])) {
            $limit = new \DateTimeImmutable($membership['end_date'] . ' 23:59:59');
            if ($limit < $to) $to = $limit;
        }
        if ($from > $to) return ['generated' => 0, 'conflicts' => 0, 'until' => $to->format('Y-m-d')];

        $generated = 0; $conflicts = 0; $reservationService = new ArenaReservationService();
        for ($day = $from; $day <= $to; $day = $day->modify('+1 day')) {
            if (!$this->occurs($membership, $day)) continue;
            $date = $day->format('Y-m-d');
            $exists = $pdo->prepare('SELECT 1 FROM sports_membership_reservations WHERE membership_id=:membership AND occurrence_date=:date');
            $exists->execute(['membership' => $membershipId, 'date' => $date]);
            if ($exists->fetchColumn()) continue;
            $start = new \DateTimeImmutable($date . ' ' . $membership['start_time']);
            try {
                $reservation = $reservationService->create(
                    $tenantId,
                    (int)$membership['court_id'],
                    (int)($membership['modality_id'] ?? 0),
                    $start,
                    (int)$membership['duration_minutes'],
                    ['id' => (int)$membership['customer_id'], 'name' => $membership['customer_name'], 'phone' => $membership['customer_phone'], 'email' => $membership['customer_email']],
                    'recurring',
                    'Mensalista #' . $membershipId,
                    substr(hash('md5', 'membership-' . $membershipId), 0, 32)
                );
                $pdo->prepare('INSERT INTO sports_membership_reservations(membership_id,reservation_id,tenant_id,occurrence_date,created_at) VALUES(:membership,:reservation,:tenant,:date,NOW())')
                    ->execute(['membership' => $membershipId, 'reservation' => $reservation['id'], 'tenant' => $tenantId, 'date' => $date]);
                $generated++;
            } catch (\DomainException $e) {
                $pdo->prepare(
                    "INSERT INTO sports_membership_conflicts(membership_id,tenant_id,occurrence_date,starts_at,reason,created_at)
                     VALUES(:membership,:tenant,:date,:starts,:reason,NOW())
                     ON DUPLICATE KEY UPDATE reason=VALUES(reason)"
                )->execute([
                    'membership' => $membershipId, 'tenant' => $tenantId, 'date' => $date,
                    'starts' => $start->format('Y-m-d H:i:s'), 'reason' => mb_substr($e->getMessage(), 0, 300),
                ]);
                $conflicts++;
            }
        }
        $next = $to->modify('+1 day')->format('Y-m-d');
        $pdo->prepare('UPDATE sports_memberships SET next_generation_date=:next,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant')
            ->execute(['next' => $next, 'id' => $membershipId, 'tenant' => $tenantId]);
        $this->ensureFinance($tenantId, $membershipId, (float)$membership['monthly_amount']);
        return ['generated' => $generated, 'conflicts' => $conflicts, 'until' => $to->format('Y-m-d')];
    }

    public function generateDue(int $tenantId, int $limit = 100): array
    {
        $pdo = Database::connection();
        $q = $pdo->prepare(
            "SELECT id FROM sports_memberships WHERE tenant_id=:tenant AND status='active'
             AND start_date<=DATE_ADD(CURDATE(),INTERVAL generate_days_ahead DAY)
             AND (end_date IS NULL OR end_date>=CURDATE())
             ORDER BY COALESCE(next_generation_date,start_date),id LIMIT " . max(1, min(500, $limit))
        );
        $q->execute(['tenant' => $tenantId]);
        $result = ['memberships' => 0, 'generated' => 0, 'conflicts' => 0];
        foreach ($q->fetchAll(\PDO::FETCH_COLUMN) as $id) {
            try {
                $one = $this->generate($tenantId, (int)$id);
                $result['memberships']++;
                $result['generated'] += (int)$one['generated'];
                $result['conflicts'] += (int)$one['conflicts'];
            } catch (\Throwable $e) {
                error_log('[ApPlanner Arena] Mensalista #' . (int)$id . ': ' . $e->getMessage());
            }
        }
        return $result;
    }

    private function ensureFinance(int $tenantId, int $membershipId, float $amount): void
    {
        if ($amount <= 0 || !ModuleService::has('finance', $tenantId)) return;
        $key = 'arena-membership-' . $membershipId . '-' . date('Ym');
        Database::connection()->prepare(
            "INSERT IGNORE INTO financial_transactions
             (tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,due_at,competence_at,created_at,updated_at)
             VALUES(:tenant,'arena_membership',:source,'income',:description,:amount,'outro','pending',:key,CURDATE(),CURDATE(),NOW(),NOW())"
        )->execute([
            'tenant' => $tenantId, 'source' => $membershipId, 'description' => 'Mensalidade Arena #' . $membershipId,
            'amount' => round($amount, 2), 'key' => $key,
        ]);
    }

    private function occurs(array $membership, \DateTimeImmutable $date): bool
    {
        $start = new \DateTimeImmutable($membership['start_date'] . ' 00:00:00');
        if ($date < $start) return false;
        if (!empty($membership['end_date']) && $date > new \DateTimeImmutable($membership['end_date'] . ' 23:59:59')) return false;
        if ($membership['frequency'] === 'monthly') return (int)$date->format('j') === (int)$membership['day_of_month'];
        if ((int)$date->format('N') !== (int)$membership['weekday']) return false;
        $anchor = $start;
        while ((int)$anchor->format('N') !== (int)$membership['weekday']) $anchor = $anchor->modify('+1 day');
        if ($date < $anchor) return false;
        $days = (int)$anchor->diff($date)->format('%a');
        $interval = $membership['frequency'] === 'biweekly' ? 14 : 7;
        return $days % $interval === 0;
    }
}
