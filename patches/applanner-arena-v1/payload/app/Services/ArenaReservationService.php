<?php
namespace App\Services;

use App\Core\{Auth, Database};

final class ArenaReservationService
{
    public function create(
        int $tenantId,
        int $courtId,
        int $modalityId,
        \DateTimeImmutable $start,
        int $durationMinutes,
        array $customer,
        string $source = 'internal',
        ?string $notes = null,
        ?string $recurrenceGroup = null,
        ?float $overrideTotal = null,
        float $depositAmount = 0,
        string $paymentMethod = 'onsite',
        string $initialStatus = 'confirmed'
    ): array {
        $pdo = Database::connection();
        $durationMinutes = max(15, min(1440, $durationMinutes));
        $end = $start->modify('+' . $durationMinutes . ' minutes');
        $lockName = 'arena|' . $tenantId . '|' . $courtId . '|' . $start->format('Ymd');
        $lock = $pdo->prepare('SELECT GET_LOCK(:lock_name,5)');
        $lock->execute(['lock_name' => $lockName]);
        if ((int)$lock->fetchColumn() !== 1) {
            throw new \DomainException('Outro usuário está concluindo uma reserva nesta quadra.');
        }

        try {
            $pdo->beginTransaction();
            $court = $pdo->prepare('SELECT * FROM sports_courts WHERE id=:court AND tenant_id=:tenant AND active=1 FOR UPDATE');
            $court->execute(['court' => $courtId, 'tenant' => $tenantId]);
            $courtRow = $court->fetch();
            if (!$courtRow) {
                throw new \DomainException('Quadra indisponível.');
            }
            $modalityId = $this->normalizeModality($pdo, $tenantId, $courtId, $modalityId);
            $availability = new SportsAvailabilityService();
            if (!$availability->free($tenantId, $courtId, $start, $end, (int)$courtRow['interval_minutes'])) {
                throw new \DomainException('A quadra não está livre no horário selecionado.');
            }
            $quote = $availability->quote($tenantId, $courtId, $modalityId, $start, $durationMinutes);
            if (!$quote && $overrideTotal === null) {
                throw new \DomainException('Não existe preço configurado para este horário.');
            }
            $hourPrice = $quote ? (float)$quote['price_per_hour'] : round((float)$overrideTotal * 60 / max(1, $durationMinutes), 2);
            $total = $overrideTotal === null ? (float)$quote['total'] : round(max(0, $overrideTotal), 2);
            $depositAmount = round(max(0, min($total, $depositAmount)), 2);

            $customerId = $this->resolveCustomer($pdo, $tenantId, $customer);
            $token = bin2hex(random_bytes(32));
            $status = in_array($initialStatus, ['pending_payment', 'confirmed'], true) ? $initialStatus : 'confirmed';
            $paymentStatus = $status === 'pending_payment' ? 'pending' : ($depositAmount > 0 ? 'pending' : 'not_required');
            $source = in_array($source, ['public', 'internal', 'recurring'], true) ? $source : 'internal';

            $insert = $pdo->prepare(
                "INSERT INTO sports_reservations
                 (public_id,tenant_id,court_id,modality_id,customer_id,customer_name,customer_phone,customer_email,starts_at,ends_at,duration_minutes,price_per_hour,total_amount,deposit_amount,status,payment_method,payment_status,manage_token_hash,recurrence_group,source,notes,terms_accepted_at,confirmed_at,created_by,created_at,updated_at)
                 VALUES(:public,:tenant,:court,:modality,:customer,:name,:phone,:email,:starts,:ends,:duration,:hour_price,:total,:deposit,:status,:method,:payment,:token,:group_id,:source,:notes,NOW(),:confirmed,:user_id,NOW(),NOW())"
            );
            $insert->execute([
                'public' => bin2hex(random_bytes(16)),
                'tenant' => $tenantId,
                'court' => $courtId,
                'modality' => $modalityId ?: null,
                'customer' => $customerId ?: null,
                'name' => trim((string)($customer['name'] ?? '')) ?: 'Reserva interna',
                'phone' => preg_replace('/\D/', '', (string)($customer['phone'] ?? '')),
                'email' => $this->email($customer['email'] ?? null),
                'starts' => $start->format('Y-m-d H:i:s'),
                'ends' => $end->format('Y-m-d H:i:s'),
                'duration' => $durationMinutes,
                'hour_price' => $hourPrice,
                'total' => $total,
                'deposit' => $depositAmount,
                'status' => $status,
                'method' => $paymentMethod === 'pix' ? 'pix' : 'onsite',
                'payment' => $paymentStatus,
                'token' => hash('sha256', $token),
                'group_id' => $recurrenceGroup,
                'source' => $source,
                'notes' => $notes,
                'confirmed' => $status === 'confirmed' ? date('Y-m-d H:i:s') : null,
                'user_id' => (int)(Auth::user()['id'] ?? 0) ?: null,
            ]);
            $reservationId = (int)$pdo->lastInsertId();
            $pdo->prepare(
                "INSERT INTO sports_reservation_history(reservation_id,action,new_status,notes,actor_user_id,created_at)
                 VALUES(:reservation,'created',:status,:notes,:user,NOW())"
            )->execute([
                'reservation' => $reservationId,
                'status' => $status,
                'notes' => $notes ?: 'Reserva criada pela Arena',
                'user' => (int)(Auth::user()['id'] ?? 0) ?: null,
            ]);
            $pdo->prepare(
                "INSERT INTO sports_reservation_finance
                 (reservation_id,tenant_id,payment_state,gross_amount,deposit_due,amount_paid,amount_refunded,fee_amount,net_amount,updated_at,created_at)
                 VALUES(:reservation,:tenant,:state,:gross,:deposit,0,0,0,:net,NOW(),NOW())
                 ON DUPLICATE KEY UPDATE gross_amount=VALUES(gross_amount),deposit_due=VALUES(deposit_due),payment_state=VALUES(payment_state),updated_at=NOW()"
            )->execute([
                'reservation' => $reservationId,
                'tenant' => $tenantId,
                'state' => $paymentStatus === 'not_required' ? 'not_required' : 'pending',
                'gross' => $total,
                'deposit' => $depositAmount,
                'net' => $total,
            ]);
            $pdo->commit();
            return [
                'id' => $reservationId,
                'manage_token' => $token,
                'starts_at' => $start->format('Y-m-d H:i:s'),
                'ends_at' => $end->format('Y-m-d H:i:s'),
                'total_amount' => $total,
                'deposit_amount' => $depositAmount,
                'status' => $status,
            ];
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            throw $e;
        } finally {
            try {
                $pdo->prepare('SELECT RELEASE_LOCK(:lock_name)')->execute(['lock_name' => $lockName]);
            } catch (\Throwable) {
            }
        }
    }

    public function recalculateCustomerMetrics(int $tenantId): void
    {
        $pdo = Database::connection();
        $customers = $pdo->prepare(
            "SELECT c.id,
                    MAX(CASE WHEN r.status IN('confirmed','completed','no_show') THEN r.starts_at END) last_reservation_at,
                    SUM(CASE WHEN r.status IN('confirmed','completed','no_show') THEN 1 ELSE 0 END) reservation_count,
                    SUM(CASE WHEN r.status='cancelled' THEN 1 ELSE 0 END) cancellation_count,
                    SUM(CASE WHEN r.status='no_show' THEN 1 ELSE 0 END) no_show_count,
                    COALESCE(SUM(CASE WHEN r.status IN('confirmed','completed') THEN r.total_amount ELSE 0 END),0) total_spent
             FROM customers c
             LEFT JOIN sports_reservations r ON r.customer_id=c.id AND r.tenant_id=c.tenant_id
             WHERE c.tenant_id=:tenant
             GROUP BY c.id"
        );
        $customers->execute(['tenant' => $tenantId]);
        foreach ($customers->fetchAll() as $row) {
            $customerId = (int)$row['id'];
            $count = (int)$row['reservation_count'];
            $spent = (float)$row['total_spent'];
            $last = $row['last_reservation_at'] ? strtotime((string)$row['last_reservation_at']) : null;
            $days = $last ? (int)floor((time() - $last) / 86400) : null;
            $segment = 'new';
            if ($count >= 10 || $spent >= 1500) $segment = 'vip';
            elseif ($days !== null && $days >= 60) $segment = 'inactive';
            elseif ($days !== null && $days >= 30) $segment = 'churn_risk';
            elseif ($count >= 2) $segment = 'recurring';
            $favCourt = $this->favorite($pdo, $tenantId, $customerId, 'court_id');
            $favModality = $this->favorite($pdo, $tenantId, $customerId, 'modality_id');
            $membership = $pdo->prepare("SELECT EXISTS(SELECT 1 FROM sports_memberships WHERE tenant_id=:tenant AND customer_id=:customer AND status='active')");
            $membership->execute(['tenant' => $tenantId, 'customer' => $customerId]);
            $games = $pdo->prepare("SELECT COUNT(*) FROM sports_game_players WHERE tenant_id=:tenant AND customer_id=:customer AND participation_status='confirmed'");
            $games->execute(['tenant' => $tenantId, 'customer' => $customerId]);
            $pdo->prepare(
                "INSERT INTO sports_customer_metrics
                 (tenant_id,customer_id,last_reservation_at,reservation_count,cancellation_count,no_show_count,total_spent,average_ticket,favorite_court_id,favorite_modality_id,is_membership,game_count,segment,updated_at)
                 VALUES(:tenant,:customer,:last,:count,:cancel,:no_show,:spent,:avg,:court,:modality,:membership,:games,:segment,NOW())
                 ON DUPLICATE KEY UPDATE last_reservation_at=VALUES(last_reservation_at),reservation_count=VALUES(reservation_count),cancellation_count=VALUES(cancellation_count),no_show_count=VALUES(no_show_count),total_spent=VALUES(total_spent),average_ticket=VALUES(average_ticket),favorite_court_id=VALUES(favorite_court_id),favorite_modality_id=VALUES(favorite_modality_id),is_membership=VALUES(is_membership),game_count=VALUES(game_count),segment=VALUES(segment),updated_at=NOW()"
            )->execute([
                'tenant' => $tenantId,
                'customer' => $customerId,
                'last' => $row['last_reservation_at'],
                'count' => $count,
                'cancel' => (int)$row['cancellation_count'],
                'no_show' => (int)$row['no_show_count'],
                'spent' => $spent,
                'avg' => $count > 0 ? round($spent / $count, 2) : 0,
                'court' => $favCourt,
                'modality' => $favModality,
                'membership' => (int)$membership->fetchColumn(),
                'games' => (int)$games->fetchColumn(),
                'segment' => $segment,
            ]);
        }
    }

    private function favorite(\PDO $pdo, int $tenantId, int $customerId, string $column): ?int
    {
        if (!in_array($column, ['court_id', 'modality_id'], true)) return null;
        $q = $pdo->prepare(
            "SELECT {$column},COUNT(*) uses_count FROM sports_reservations
             WHERE tenant_id=:tenant AND customer_id=:customer AND {$column} IS NOT NULL AND status IN('confirmed','completed','no_show')
             GROUP BY {$column} ORDER BY uses_count DESC,MAX(starts_at) DESC LIMIT 1"
        );
        $q->execute(['tenant' => $tenantId, 'customer' => $customerId]);
        $value = $q->fetchColumn();
        return $value === false ? null : (int)$value;
    }

    private function normalizeModality(\PDO $pdo, int $tenantId, int $courtId, int $modalityId): int
    {
        if ($modalityId > 0) {
            $q = $pdo->prepare(
                'SELECT m.id FROM sports_modalities m JOIN sports_court_modalities cm ON cm.modality_id=m.id
                 WHERE m.id=:modality AND m.tenant_id=:tenant AND cm.court_id=:court AND m.active=1 LIMIT 1'
            );
            $q->execute(['modality' => $modalityId, 'tenant' => $tenantId, 'court' => $courtId]);
            if ($q->fetchColumn()) return $modalityId;
        }
        $q = $pdo->prepare(
            'SELECT m.id FROM sports_modalities m JOIN sports_court_modalities cm ON cm.modality_id=m.id
             WHERE m.tenant_id=:tenant AND cm.court_id=:court AND m.active=1 ORDER BY m.sort_order,m.name LIMIT 1'
        );
        $q->execute(['tenant' => $tenantId, 'court' => $courtId]);
        $fallback = (int)$q->fetchColumn();
        if ($fallback <= 0) throw new \DomainException('A quadra não possui modalidade ativa.');
        return $fallback;
    }

    private function resolveCustomer(\PDO $pdo, int $tenantId, array $customer): int
    {
        $id = (int)($customer['id'] ?? 0);
        if ($id > 0) {
            $q = $pdo->prepare("SELECT id FROM customers WHERE id=:id AND tenant_id=:tenant AND status='active'");
            $q->execute(['id' => $id, 'tenant' => $tenantId]);
            if ($q->fetchColumn()) return $id;
        }
        $phone = preg_replace('/\D/', '', (string)($customer['phone'] ?? ''));
        if ($phone !== '') {
            $q = $pdo->prepare('SELECT id FROM customers WHERE tenant_id=:tenant AND phone=:phone LIMIT 1');
            $q->execute(['tenant' => $tenantId, 'phone' => $phone]);
            $existing = (int)$q->fetchColumn();
            if ($existing > 0) return $existing;
        }
        $name = trim((string)($customer['name'] ?? ''));
        if ($name === '') return 0;
        $pdo->prepare(
            "INSERT INTO customers(tenant_id,name,phone,email,status,created_at,updated_at)
             VALUES(:tenant,:name,:phone,:email,'active',NOW(),NOW())"
        )->execute([
            'tenant' => $tenantId,
            'name' => $name,
            'phone' => $phone,
            'email' => $this->email($customer['email'] ?? null),
        ]);
        return (int)$pdo->lastInsertId();
    }

    private function email(mixed $email): ?string
    {
        $email = mb_strtolower(trim((string)$email));
        return $email !== '' && filter_var($email, FILTER_VALIDATE_EMAIL) ? $email : null;
    }
}
