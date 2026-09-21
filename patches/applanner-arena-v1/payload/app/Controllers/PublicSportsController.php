<?php
namespace App\Controllers;

use App\Core\{CSRF,Database,HttpException,RateLimiter,View};
use App\Services\{ModuleService,SportsAvailabilityService,TenantPaymentService};

final class PublicSportsController
{
    public function show(string $slug): void
    {
        $pdo = Database::connection();
        $tenant = $this->tenant($pdo, $slug);
        if (!$tenant) HttpException::abort(404, 'Arena não encontrada.');
        $canonical = trim((string)($tenant['public_slug'] ?? ''));
        if ($canonical !== '' && strcasecmp($slug, $canonical) !== 0) {
            header('Location: /arena/' . rawurlencode($canonical), true, 302);
            exit;
        }
        $courts = $pdo->prepare(
            "SELECT c.*,u.name unit_name,
                    GROUP_CONCAT(DISTINCT m.name ORDER BY m.name SEPARATOR ', ') modalities,
                    GROUP_CONCAT(DISTINCT cm.modality_id ORDER BY cm.modality_id) modality_ids
             FROM sports_courts c
             LEFT JOIN units u ON u.id=c.unit_id
             LEFT JOIN sports_court_modalities cm ON cm.court_id=c.id
             LEFT JOIN sports_modalities m ON m.id=cm.modality_id
             WHERE c.tenant_id=:tenant AND c.active=1
             GROUP BY c.id,u.name ORDER BY c.sort_order,c.name"
        );
        $courts->execute(['tenant' => $tenant['id']]);
        $mods = $pdo->prepare('SELECT id,name,description FROM sports_modalities WHERE tenant_id=:tenant AND active=1 ORDER BY sort_order,name');
        $mods->execute(['tenant' => $tenant['id']]);
        $settings = $this->settings($pdo, (int)$tenant['id']);
        $arenaSettings = $this->arenaSettings($pdo, (int)$tenant['id']);
        $selectedCourt = trim((string)($_GET['quadra'] ?? ''));
        View::render('public/sports', [
            'title' => 'Reserve sua quadra · ' . $tenant['name'],
            'tenant' => $tenant,
            'routeSlug' => $canonical ?: $slug,
            'courts' => $courts->fetchAll() ?: [],
            'modalities' => $mods->fetchAll() ?: [],
            'settings' => $settings,
            'arenaSettings' => $arenaSettings,
            'selectedCourtSlug' => $selectedCourt,
            'publicLayout' => true,
        ]);
    }

    public function availability(string $slug): void
    {
        $pdo = Database::connection();
        $tenant = $this->tenant($pdo, $slug);
        if (!$tenant) { $this->json(['error' => 'Indisponível'], 404); return; }
        $court = (int)($_GET['court_id'] ?? 0);
        $modality = (int)($_GET['modality_id'] ?? 0);
        $date = (string)($_GET['date'] ?? '');
        $duration = max(15, min(1440, (int)($_GET['duration_minutes'] ?? 60)));
        if (!$court || !$modality || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) { $this->json(['slots' => []]); return; }
        $service = new SportsAvailabilityService();
        $slots = $service->slots((int)$tenant['id'], $court, $modality, $date, $duration);
        $next = $slots ? null : $service->nextAvailableDate((int)$tenant['id'], $court, $modality, $date, $duration);
        $this->json(['slots' => $slots, 'next_available_date' => $next]);
    }

    public function book(string $slug): void
    {
        CSRF::enforce();
        $ip = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
        if (!RateLimiter::hit('sports-book|' . $ip, 8, 3600)) HttpException::abort(429, 'Muitas tentativas. Aguarde alguns minutos.');

        $pdo = Database::connection();
        $tenant = $this->tenant($pdo, $slug);
        if (!$tenant) HttpException::abort(404, 'Arena indisponível.');
        $tenantId = (int)$tenant['id'];
        $court = (int)($_POST['court_id'] ?? 0);
        $modality = (int)($_POST['modality_id'] ?? 0);
        $duration = max(15, min(1440, (int)($_POST['duration_minutes'] ?? 60)));
        $name = trim((string)($_POST['name'] ?? ''));
        $phone = preg_replace('/\D/', '', (string)($_POST['phone'] ?? ''));
        $email = mb_strtolower(trim((string)($_POST['email'] ?? '')));
        if (mb_strlen($name) < 2 || strlen($phone) < 10 || ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) || !isset($_POST['terms'])) {
            HttpException::abort(422, 'Revise seus dados e aceite as condições da reserva.');
        }
        try { $start = new \DateTimeImmutable((string)($_POST['starts_at'] ?? '')); }
        catch (\Throwable) { HttpException::abort(422, 'Horário inválido.'); }

        $service = new SportsAvailabilityService();
        $valid = array_filter(
            $service->slots($tenantId, $court, $modality, $start->format('Y-m-d'), $duration),
            fn($slot) => $slot['value'] === $start->format('Y-m-d H:i:s')
        );
        if (!$valid) HttpException::abort(409, 'Este horário não está mais disponível. Atualize a agenda.');
        $slot = array_values($valid)[0];
        $end = $start->modify('+' . $duration . ' minutes');
        $settings = $this->settings($pdo, $tenantId);
        $arenaSettings = $this->arenaSettings($pdo, $tenantId);
        $deposit = !empty($settings['require_deposit'])
            ? ($settings['deposit_type'] === 'fixed'
                ? (float)$settings['deposit_value']
                : round((float)$slot['total'] * (float)$settings['deposit_value'] / 100, 2))
            : 0.0;
        $deposit = min((float)$slot['total'], max(0, $deposit));

        $payments = new TenantPaymentService();
        $autoConnection = null;
        if ($deposit > 0 && ModuleService::has('banking_integrations', $tenantId)) {
            try { $autoConnection = $payments->connected($tenantId); } catch (\Throwable) { $autoConnection = null; }
        }
        if ($deposit > 0 && !$autoConnection && empty($settings['pix_key'])) {
            HttpException::abort(422, 'A Arena ainda não configurou uma forma de receber o sinal.');
        }
        if ($deposit > 0 && $autoConnection && $email === '' && empty($settings['pix_key'])) {
            HttpException::abort(422, 'Informe seu e-mail para gerar o Pix automático.');
        }
        $method = $deposit > 0 ? 'pix' : ((($_POST['payment_method'] ?? 'onsite') === 'pix') ? 'pix' : 'onsite');

        $lockName = 'sports|' . $tenantId . '|' . $court . '|' . $start->format('Ymd');
        $lock = $pdo->prepare('SELECT GET_LOCK(:lock,5)');
        $lock->execute(['lock' => $lockName]);
        if ((int)$lock->fetchColumn() !== 1) HttpException::abort(409, 'Outro cliente está concluindo este horário. Tente novamente.');
        $rawToken = bin2hex(random_bytes(32));
        try {
            $pdo->beginTransaction();
            $courtQuery = $pdo->prepare('SELECT interval_minutes FROM sports_courts WHERE id=:court AND tenant_id=:tenant FOR UPDATE');
            $courtQuery->execute(['court' => $court, 'tenant' => $tenantId]);
            $courtBuffer = $courtQuery->fetchColumn();
            if ($courtBuffer === false) throw new \DomainException('Quadra indisponível.');
            $customer = $this->customer($pdo, $tenantId, $name, $phone, $email);
            if (!$service->free($tenantId, $court, $start, $end, (int)$courtBuffer)) throw new \DomainException('O horário acabou de ser reservado.');

            $status = $deposit > 0 ? 'pending_payment' : 'confirmed';
            $paymentStatus = $deposit > 0 ? 'pending' : 'not_required';
            $pdo->prepare(
                "INSERT INTO sports_reservations
                 (public_id,tenant_id,court_id,modality_id,customer_id,customer_name,customer_phone,customer_email,starts_at,ends_at,duration_minutes,price_per_hour,total_amount,deposit_amount,status,payment_method,payment_status,manage_token_hash,source,notes,terms_accepted_at,confirmed_at,created_at,updated_at)
                 VALUES(:public,:tenant,:court,:modality,:customer,:name,:phone,:email,:starts,:ends,:duration,:hour_price,:total,:deposit,:status,:method,:payment,:token,'public',:notes,NOW(),:confirmed,NOW(),NOW())"
            )->execute([
                'public' => bin2hex(random_bytes(16)), 'tenant' => $tenantId, 'court' => $court, 'modality' => $modality,
                'customer' => $customer, 'name' => $name, 'phone' => $phone, 'email' => $email ?: null,
                'starts' => $start->format('Y-m-d H:i:s'), 'ends' => $end->format('Y-m-d H:i:s'), 'duration' => $duration,
                'hour_price' => $slot['price_per_hour'], 'total' => $slot['total'], 'deposit' => $deposit,
                'status' => $status, 'method' => $method, 'payment' => $paymentStatus, 'token' => hash('sha256', $rawToken),
                'notes' => trim((string)($_POST['notes'] ?? '')) ?: null,
                'confirmed' => $status === 'confirmed' ? date('Y-m-d H:i:s') : null,
            ]);
            $reservationId = (int)$pdo->lastInsertId();
            $pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,new_status,notes,created_at) VALUES(:reservation,'created',:status,'Reserva pública Arena',NOW())")
                ->execute(['reservation' => $reservationId, 'status' => $status]);
            $expiresAt = $deposit > 0
                ? (new \DateTimeImmutable('+' . max(1, (int)$arenaSettings['payment_deadline_minutes']) . ' minutes'))->format('Y-m-d H:i:s')
                : null;
            $pdo->prepare(
                "INSERT INTO sports_reservation_finance(reservation_id,tenant_id,payment_state,gross_amount,deposit_due,amount_paid,amount_refunded,fee_amount,net_amount,expires_at,updated_at,created_at)
                 VALUES(:reservation,:tenant,:state,:gross,:deposit,0,0,0,:net,:expires,NOW(),NOW())"
            )->execute([
                'reservation' => $reservationId, 'tenant' => $tenantId, 'state' => $deposit > 0 ? 'pending' : 'not_required',
                'gross' => $slot['total'], 'deposit' => $deposit, 'net' => $slot['total'], 'expires' => $expiresAt,
            ]);
            $pdo->commit();
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            if ($e instanceof \DomainException) HttpException::abort(409, $e->getMessage());
            throw $e;
        } finally {
            $pdo->prepare('SELECT RELEASE_LOCK(:lock)')->execute(['lock' => $lockName]);
        }

        if ($deposit > 0 && $autoConnection && $email !== '') {
            try {
                $tx = $payments->createPix($tenantId, 'reservation', $reservationId, $deposit, $email, (int)$arenaSettings['payment_deadline_minutes']);
                $pdo->prepare(
                    "UPDATE sports_reservation_finance SET provider='mercadopago',external_reference=:external,transaction_id=:transaction,expires_at=:expires,updated_at=NOW()
                     WHERE reservation_id=:reservation AND tenant_id=:tenant"
                )->execute([
                    'external' => $tx['external_reference'] ?? null, 'transaction' => $tx['provider_transaction_id'] ?? null,
                    'expires' => $tx['expires_at'] ?? null, 'reservation' => $reservationId, 'tenant' => $tenantId,
                ]);
            } catch (\Throwable $e) {
                error_log('[ApPlanner Arena] Falha no Pix automático da reserva ' . $reservationId . ': ' . $e->getMessage());
            }
        }

        header('Location: /arena/reserva/' . $rawToken);
        exit;
    }

    public function manage(string $token): void
    {
        $pdo = Database::connection();
        $reservation = $this->reservation($pdo, $token);
        $settings = $this->settings($pdo, (int)$reservation['tenant_id']);
        $finance = $pdo->prepare('SELECT * FROM sports_reservation_finance WHERE reservation_id=:reservation AND tenant_id=:tenant');
        $finance->execute(['reservation' => $reservation['id'], 'tenant' => $reservation['tenant_id']]);
        $financeRow = $finance->fetch() ?: null;
        $transaction = null;
        if ($financeRow) {
            $q = $pdo->prepare("SELECT * FROM tenant_payment_transactions WHERE tenant_id=:tenant AND reference_type='reservation' AND reference_id=:reservation ORDER BY id DESC LIMIT 1");
            $q->execute(['tenant' => $reservation['tenant_id'], 'reservation' => $reservation['id']]);
            $transaction = $q->fetch() ?: null;
        }
        View::render('public/sports-manage', [
            'title' => 'Sua reserva', 'reservation' => $reservation, 'settings' => $settings,
            'finance' => $financeRow, 'transaction' => $transaction, 'token' => $token, 'publicLayout' => true,
        ]);
    }

    public function reservationAvailability(string $token): void
    {
        $pdo = Database::connection();
        $reservation = $this->reservation($pdo, $token);
        if ($reservation['status'] !== 'confirmed') { $this->json(['slots' => []], 409); return; }
        $date = (string)($_GET['date'] ?? '');
        $duration = max(15, min(1440, (int)($_GET['duration_minutes'] ?? $reservation['duration_minutes'])));
        if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) { $this->json(['slots' => []]); return; }
        $slots = (new SportsAvailabilityService())->slots(
            (int)$reservation['tenant_id'], (int)$reservation['court_id'], (int)$reservation['modality_id'],
            $date, $duration, (int)$reservation['id']
        );
        $this->json(['slots' => $slots]);
    }

    public function reschedule(string $token): void
    {
        CSRF::enforce();
        $pdo = Database::connection();
        $reservation = $this->reservation($pdo, $token);
        if ($reservation['status'] !== 'confirmed') HttpException::abort(409, 'Somente reservas confirmadas podem ser remarcadas online.');
        $settings = $this->settings($pdo, (int)$reservation['tenant_id']);
        $limit = (new \DateTimeImmutable($reservation['starts_at']))->modify('-' . (int)$settings['cancellation_notice_minutes'] . ' minutes');
        if (new \DateTimeImmutable() > $limit) HttpException::abort(409, 'O prazo de remarcação online terminou. Entre em contato com a Arena.');
        $duration = max(15, min(1440, (int)($_POST['duration_minutes'] ?? $reservation['duration_minutes'])));
        try { $start = new \DateTimeImmutable((string)($_POST['starts_at'] ?? '')); }
        catch (\Throwable) { HttpException::abort(422, 'Novo horário inválido.'); }
        $service = new SportsAvailabilityService();
        $slots = $service->slots((int)$reservation['tenant_id'], (int)$reservation['court_id'], (int)$reservation['modality_id'], $start->format('Y-m-d'), $duration, (int)$reservation['id']);
        $slot = null;
        foreach ($slots as $candidate) if ($candidate['value'] === $start->format('Y-m-d H:i:s')) { $slot = $candidate; break; }
        if (!$slot) HttpException::abort(409, 'O novo horário não está disponível.');

        $tenantId=(int)$reservation['tenant_id'];$courtId=(int)$reservation['court_id'];
        $lockName='sports-reschedule|'.$tenantId.'|'.$courtId.'|'.$start->format('Ymd');
        $lock=$pdo->prepare('SELECT GET_LOCK(:lock,5)');$lock->execute(['lock'=>$lockName]);
        if((int)$lock->fetchColumn()!==1)HttpException::abort(409,'Outro cliente está concluindo uma reserva nesta quadra.');
        try {
            $pdo->beginTransaction();
            $row=$pdo->prepare("SELECT r.*,c.interval_minutes FROM sports_reservations r JOIN sports_courts c ON c.id=r.court_id AND c.tenant_id=r.tenant_id WHERE r.id=:id AND r.tenant_id=:tenant FOR UPDATE");
            $row->execute(['id'=>$reservation['id'],'tenant'=>$tenantId]);$current=$row->fetch();
            if(!$current||$current['status']!=='confirmed')throw new \DomainException('A reserva não pode mais ser remarcada.');
            $end=$start->modify('+'.$duration.' minutes');
            if(!$service->free($tenantId,$courtId,$start,$end,(int)$current['interval_minutes'],(int)$current['id']))throw new \DomainException('O novo horário acabou de ser ocupado.');
            $oldStart=$current['starts_at'];$oldEnd=$current['ends_at'];$oldTotal=(float)$current['total_amount'];
            $newDeposit=min((float)$current['deposit_amount'],(float)$slot['total']);
            $pdo->prepare("UPDATE sports_reservations SET starts_at=:starts,ends_at=:ends,duration_minutes=:duration,price_per_hour=:hour,total_amount=:total,deposit_amount=:deposit,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['starts'=>$start->format('Y-m-d H:i:s'),'ends'=>$end->format('Y-m-d H:i:s'),'duration'=>$duration,'hour'=>$slot['price_per_hour'],'total'=>$slot['total'],'deposit'=>$newDeposit,'id'=>$current['id'],'tenant'=>$tenantId]);
            $pdo->prepare("UPDATE sports_reservation_finance SET gross_amount=:gross,deposit_due=:deposit,net_amount=:gross2,payment_state=CASE WHEN amount_paid>=:gross3 THEN 'paid' WHEN amount_paid>0 THEN 'partial' ELSE payment_state END,updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant")
                ->execute(['gross'=>$slot['total'],'deposit'=>$newDeposit,'gross2'=>$slot['total'],'gross3'=>$slot['total'],'id'=>$current['id'],'tenant'=>$tenantId]);
            $pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,created_at) VALUES(:id,'rescheduled_by_customer','confirmed','confirmed',:notes,NOW())")
                ->execute(['id'=>$current['id'],'notes'=>'De '.$oldStart.'–'.$oldEnd.' para '.$start->format('Y-m-d H:i:s').'–'.$end->format('Y-m-d H:i:s').'; valor '.$oldTotal.' → '.$slot['total']]);
            $pdo->commit();
        } catch(\DomainException $e){if($pdo->inTransaction())$pdo->rollBack();HttpException::abort(409,$e->getMessage());}
          catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
        finally{try{$pdo->prepare('SELECT RELEASE_LOCK(:lock)')->execute(['lock'=>$lockName]);}catch(\Throwable){}}
        header('Location: /arena/reserva/'.$token.'?rescheduled=1');exit;
    }

    public function cancel(string $token): void
    {
        CSRF::enforce();
        $pdo = Database::connection();
        $reservation = $this->reservation($pdo, $token);
        if (!in_array($reservation['status'], ['pending_payment','confirmed'], true)) HttpException::abort(409, 'Esta reserva não pode mais ser cancelada.');
        $settings = $this->settings($pdo, (int)$reservation['tenant_id']);
        $limit = (new \DateTimeImmutable($reservation['starts_at']))->modify('-' . (int)$settings['cancellation_notice_minutes'] . ' minutes');
        if (new \DateTimeImmutable() > $limit) HttpException::abort(409, 'O prazo de cancelamento online terminou. Entre em contato com a Arena.');
        $pdo->beginTransaction();
        try {
            $pdo->prepare("UPDATE sports_reservations SET status='cancelled',payment_status=IF(payment_status='pending','cancelled',payment_status),cancelled_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['id' => $reservation['id'], 'tenant' => $reservation['tenant_id']]);
            $pdo->prepare("UPDATE sports_reservation_finance SET payment_state=IF(payment_state='pending','cancelled',payment_state),updated_at=NOW() WHERE reservation_id=:id AND tenant_id=:tenant")
                ->execute(['id' => $reservation['id'], 'tenant' => $reservation['tenant_id']]);
            $pdo->prepare("UPDATE tenant_payment_transactions SET status=IF(status IN('created','pending'),'cancelled',status),updated_at=NOW() WHERE tenant_id=:tenant AND reference_type='reservation' AND reference_id=:id")
                ->execute(['tenant' => $reservation['tenant_id'], 'id' => $reservation['id']]);
            $pdo->prepare("INSERT INTO sports_reservation_history(reservation_id,action,old_status,new_status,notes,created_at) VALUES(:reservation,'cancelled_by_customer',:old,'cancelled','Cancelamento pelo link público',NOW())")
                ->execute(['reservation' => $reservation['id'], 'old' => $reservation['status']]);
            $pdo->commit();
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            throw $e;
        }
        header('Location: /arena/reserva/' . $token);
        exit;
    }

    private function tenant(\PDO $pdo, string $slug): array|false
    {
        $q = $pdo->prepare(
            "SELECT t.* FROM tenants t
             JOIN subscriptions s ON s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=t.id)
             JOIN modules m ON m.slug='sports_courts' AND m.active=1
             LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id
             LEFT JOIN tenant_modules tm ON tm.tenant_id=t.id AND tm.module_id=m.id
             LEFT JOIN sports_settings ss ON ss.tenant_id=t.id
             WHERE (t.public_slug=:slug OR t.public_short_code=:code) AND t.status IN('trial','active') AND t.deleted_at IS NULL
               AND COALESCE(tm.enabled,pm.enabled,0)=1 AND COALESCE(ss.public_enabled,1)=1 LIMIT 1"
        );
        $q->execute(['slug' => $slug, 'code' => $slug]);
        return $q->fetch();
    }

    private function settings(\PDO $pdo, int $tenantId): array
    {
        $q = $pdo->prepare('SELECT * FROM sports_settings WHERE tenant_id=:tenant');
        $q->execute(['tenant' => $tenantId]);
        return $q->fetch() ?: [
            'public_enabled' => 1, 'default_slot_minutes' => 60, 'minimum_notice_minutes' => 60,
            'maximum_days_ahead' => 90, 'cancellation_notice_minutes' => 720, 'require_deposit' => 0,
            'deposit_type' => 'percent', 'deposit_value' => 0, 'pix_key' => null, 'pix_holder' => null, 'booking_terms' => null,
        ];
    }

    private function arenaSettings(\PDO $pdo, int $tenantId): array
    {
        try {
            $q = $pdo->prepare('SELECT * FROM sports_arena_settings WHERE tenant_id=:tenant');
            $q->execute(['tenant' => $tenantId]);
            $row = $q->fetch();
            if ($row) return $row;
        } catch (\Throwable) {}
        return [
            'payment_deadline_minutes' => 10, 'waitlist_offer_minutes' => 10, 'allow_waitlist' => 1,
            'allow_games' => 1, 'dynamic_pricing_enabled' => 0, 'amenities_json' => null,
            'public_rules' => null, 'cancellation_policy' => null,
        ];
    }

    private function customer(\PDO $pdo, int $tenantId, string $name, string $phone, string $email): int
    {
        $q = $pdo->prepare('SELECT id FROM customers WHERE tenant_id=:tenant AND phone=:phone LIMIT 1');
        $q->execute(['tenant' => $tenantId, 'phone' => $phone]);
        $customer = (int)$q->fetchColumn();
        if ($customer) return $customer;
        $pdo->prepare("INSERT INTO customers(tenant_id,name,phone,email,status,created_at,updated_at) VALUES(:tenant,:name,:phone,:email,'active',NOW(),NOW())")
            ->execute(['tenant' => $tenantId, 'name' => $name, 'phone' => $phone, 'email' => $email ?: null]);
        return (int)$pdo->lastInsertId();
    }

    private function reservation(\PDO $pdo, string $token): array
    {
        $q = $pdo->prepare(
            "SELECT r.*,c.name court_name,m.name modality_name,t.name tenant_name,t.public_slug,t.public_short_code,u.name unit_name
             FROM sports_reservations r JOIN sports_courts c ON c.id=r.court_id JOIN tenants t ON t.id=r.tenant_id
             LEFT JOIN sports_modalities m ON m.id=r.modality_id LEFT JOIN units u ON u.id=c.unit_id
             WHERE r.manage_token_hash=:token LIMIT 1"
        );
        $q->execute(['token' => hash('sha256', $token)]);
        $reservation = $q->fetch();
        if (!$reservation) HttpException::abort(404, 'Reserva não encontrada.');
        return $reservation;
    }

    private function json(array $data, int $status = 200): void
    {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
    }
}
