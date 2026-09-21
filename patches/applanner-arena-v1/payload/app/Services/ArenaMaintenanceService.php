<?php
namespace App\Services;

use App\Core\Database;

final class ArenaMaintenanceService
{
    public function runTenant(int $tenantId): array
    {
        $result = ['expired' => 0, 'membership_generated' => 0, 'membership_conflicts' => 0, 'waitlist_offers' => 0];
        $result['expired'] = $this->expireReservations($tenantId);
        $memberships = (new ArenaMembershipService())->generateDue($tenantId);
        $result['membership_generated'] = (int)$memberships['generated'];
        $result['membership_conflicts'] = (int)$memberships['conflicts'];
        $result['waitlist_offers'] = $this->matchWaitlist($tenantId);
        (new ArenaReservationService())->recalculateCustomerMetrics($tenantId);
        return $result;
    }

    private function expireReservations(int $tenantId): int
    {
        $pdo = Database::connection();
        $q = $pdo->prepare(
            "SELECT f.reservation_id FROM sports_reservation_finance f
             JOIN sports_reservations r ON r.id=f.reservation_id AND r.tenant_id=f.tenant_id
             WHERE f.tenant_id=:tenant AND f.payment_state='pending' AND f.expires_at IS NOT NULL AND f.expires_at<NOW()
               AND r.status='pending_payment' ORDER BY f.expires_at LIMIT 200"
        );
        $q->execute(['tenant' => $tenantId]);
        $count = 0;
        foreach ($q->fetchAll(\PDO::FETCH_COLUMN) as $reservationId) {
            $pdo->beginTransaction();
            try {
                $lock = $pdo->prepare("SELECT status FROM sports_reservations WHERE id=:id AND tenant_id=:tenant FOR UPDATE");
                $lock->execute(['id' => (int)$reservationId, 'tenant' => $tenantId]);
                if ($lock->fetchColumn() !== 'pending_payment') { $pdo->rollBack(); continue; }
                $pdo->prepare("UPDATE sports_reservations SET status='cancelled',payment_status='cancelled',cancelled_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                    ->execute(['id' => (int)$reservationId, 'tenant' => $tenantId]);
                $pdo->prepare("UPDATE sports_reservation_finance SET payment_state='expired',updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant")
                    ->execute(['id' => (int)$reservationId, 'tenant' => $tenantId]);
                $pdo->prepare("UPDATE tenant_payment_transactions SET status='expired',updated_at=NOW() WHERE tenant_id=:tenant AND reference_type='reservation' AND reference_id=:id AND status IN('created','pending')")
                    ->execute(['tenant' => $tenantId, 'id' => (int)$reservationId]);
                $pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,created_at) VALUES(:id,'payment_expired','pending_payment','cancelled','Prazo do sinal expirado; horário liberado',NOW())")
                    ->execute(['id' => (int)$reservationId]);
                $pdo->commit(); $count++;
            } catch (\Throwable $e) {
                if ($pdo->inTransaction()) $pdo->rollBack();
                error_log('[ApPlanner Arena] Expiração reserva #' . (int)$reservationId . ': ' . $e->getMessage());
            }
        }
        return $count;
    }

    private function matchWaitlist(int $tenantId): int
    {
        $pdo = Database::connection();
        $settings = $pdo->prepare('SELECT waitlist_offer_minutes,allow_waitlist FROM sports_arena_settings WHERE tenant_id=:tenant');
        $settings->execute(['tenant' => $tenantId]);
        $cfg = $settings->fetch() ?: ['waitlist_offer_minutes' => 10, 'allow_waitlist' => 1];
        if (empty($cfg['allow_waitlist'])) return 0;

        // Ofertas expiradas voltam à fila para que outra oportunidade possa ser calculada.
        $pdo->prepare("UPDATE sports_waitlist SET status='waiting',offer_expires_at=NULL,offered_at=NULL,updated_at=NOW() WHERE tenant_id=:tenant AND status='offered' AND offer_expires_at<NOW()")
            ->execute(['tenant' => $tenantId]);
        $q = $pdo->prepare(
            "SELECT * FROM sports_waitlist WHERE tenant_id=:tenant AND status='waiting' AND preferred_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(),INTERVAL 30 DAY)
             ORDER BY preferred_date,id LIMIT 100"
        );
        $q->execute(['tenant' => $tenantId]);
        $availability = new SportsAvailabilityService(); $offered = 0;
        foreach ($q->fetchAll() as $entry) {
            $courtIds = [];
            if (!empty($entry['court_id'])) $courtIds = [(int)$entry['court_id']];
            else {
                $courts = $pdo->prepare('SELECT id FROM sports_courts WHERE tenant_id=:tenant AND active=1 ORDER BY sort_order,id');
                $courts->execute(['tenant' => $tenantId]); $courtIds = array_map('intval', $courts->fetchAll(\PDO::FETCH_COLUMN));
            }
            foreach ($courtIds as $courtId) {
                $modalityId = (int)($entry['modality_id'] ?? 0);
                if ($modalityId <= 0) {
                    $m = $pdo->prepare('SELECT modality_id FROM sports_court_modalities WHERE court_id=:court ORDER BY modality_id LIMIT 1');
                    $m->execute(['court' => $courtId]); $modalityId = (int)$m->fetchColumn();
                }
                if ($modalityId <= 0) continue;
                try { $slots = $availability->slots($tenantId, $courtId, $modalityId, $entry['preferred_date'], (int)$entry['duration_minutes']); }
                catch (\Throwable) { $slots = []; }
                if (!$slots) continue;
                $preferred = $entry['preferred_start'] ? strtotime($entry['preferred_date'] . ' ' . $entry['preferred_start']) : null;
                $flex = (int)$entry['flexibility_minutes'] * 60;
                $match = null;
                foreach ($slots as $slot) {
                    $time = strtotime($slot['value']);
                    if ($preferred === null || abs($time - $preferred) <= $flex) { $match = $slot; break; }
                }
                if (!$match) continue;
                $expires = (new \DateTimeImmutable('+' . max(1, (int)$cfg['waitlist_offer_minutes']) . ' minutes'))->format('Y-m-d H:i:s');
                $offerUpdate = $pdo->prepare("UPDATE sports_waitlist SET status='offered',court_id=:court,modality_id=:modality,offered_at=NOW(),offer_expires_at=:expires,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant AND status='waiting'");
                $offerUpdate->execute(['court' => $courtId, 'modality' => $modalityId, 'expires' => $expires, 'id' => $entry['id'], 'tenant' => $tenantId]);
                if ($offerUpdate->rowCount() > 0) {
                    $pdo->prepare("INSERT INTO sports_automation_logs(tenant_id,automation_key,entity_type,entity_id,channel,status,detail,created_at) VALUES(:tenant,'waitlist.match','sports_waitlist',:id,NULL,'skipped',:detail,NOW())")
                        ->execute(['tenant' => $tenantId, 'id' => $entry['id'], 'detail' => 'Vaga encontrada em ' . $match['value'] . '. Disparo externo depende de canal/consentimento configurado.']);
                    $offered++;
                }
                break;
            }
        }
        return $offered;
    }
}
