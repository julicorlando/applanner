<?php
namespace App\Controllers;

use App\Core\{CSRF,Database,HttpException,RateLimiter,View};
use App\Services\{ArenaReservationService,ModuleService,SportsAvailabilityService,TenantPaymentService};

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
        $cardAvailable=false; $waitlistOffer=null;
        try { $cardAvailable=ModuleService::has('banking_integrations',(int)$tenant['id']) && (new TenantPaymentService())->publicCardConfig((int)$tenant['id'])!==null; } catch (\Throwable) {}
        $offerToken=trim((string)($_GET['waitlist_offer']??''));
        if($offerToken!=='') $waitlistOffer=$this->waitlistOffer($pdo,(int)$tenant['id'],$offerToken);
        View::render('public/sports', [
            'title' => 'Reserve sua quadra · ' . $tenant['name'],
            'tenant' => $tenant,
            'routeSlug' => $canonical ?: $slug,
            'courts' => $courts->fetchAll() ?: [],
            'modalities' => $mods->fetchAll() ?: [],
            'settings' => $settings,
            'arenaSettings' => $arenaSettings,
            'selectedCourtSlug' => $selectedCourt,
            'cardAvailable' => $cardAvailable,
            'waitlistOffer' => $waitlistOffer,
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
        $waitlistId = null;
        $waitToken = trim((string)($_GET['waitlist_token'] ?? ''));
        if ($waitToken !== '') { $offer = $this->waitlistOffer($pdo, (int)$tenant['id'], $waitToken); if ($offer) $waitlistId = (int)$offer['id']; }
        $slots = $service->slots((int)$tenant['id'], $court, $modality, $date, $duration, null, $waitlistId);
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
        $court = (int)($_POST['court_id'] ?? 0); $modality = (int)($_POST['modality_id'] ?? 0);
        $duration = max(15, min(1440, (int)($_POST['duration_minutes'] ?? 60)));
        $name = trim((string)($_POST['name'] ?? '')); $phone = preg_replace('/\D/', '', (string)($_POST['phone'] ?? ''));
        $email = mb_strtolower(trim((string)($_POST['email'] ?? '')));
        if (mb_strlen($name) < 2 || strlen($phone) < 10 || ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) || !isset($_POST['terms'])) {
            HttpException::abort(422, 'Revise seus dados e aceite as condições da reserva.');
        }
        try { $start = new \DateTimeImmutable((string)($_POST['starts_at'] ?? '')); } catch (\Throwable) { HttpException::abort(422, 'Horário inválido.'); }

        $waitToken = trim((string)($_POST['waitlist_token'] ?? ''));
        $offer = $waitToken !== '' ? $this->waitlistOffer($pdo, $tenantId, $waitToken) : null;
        if ($waitToken !== '' && !$offer) HttpException::abort(409, 'A oferta da lista de espera expirou ou não está mais disponível.');
        if ($offer && ((int)$offer['court_id'] !== $court || (int)$offer['modality_id'] !== $modality)) HttpException::abort(422, 'A oferta é válida somente para a quadra e modalidade indicadas.');

        $availability = new SportsAvailabilityService();
        $slots = $availability->slots($tenantId, $court, $modality, $start->format('Y-m-d'), $duration, null, $offer ? (int)$offer['id'] : null);
        $slot = null; foreach ($slots as $candidate) if ($candidate['value'] === $start->format('Y-m-d H:i:s')) { $slot = $candidate; break; }
        if (!$slot) HttpException::abort(409, 'Este horário não está mais disponível. Atualize a agenda.');

        $settings = $this->settings($pdo, $tenantId); $arenaSettings = $this->arenaSettings($pdo, $tenantId);
        $deposit = !empty($settings['require_deposit'])
            ? ($settings['deposit_type'] === 'fixed' ? (float)$settings['deposit_value'] : round((float)$slot['total'] * (float)$settings['deposit_value'] / 100, 2)) : 0.0;
        $deposit = min((float)$slot['total'], max(0, $deposit));
        $payments = new TenantPaymentService(); $connection = null; $cardAvailable = false;
        if ($deposit > 0 && ModuleService::has('banking_integrations', $tenantId)) {
            try { $connection = $payments->connected($tenantId); $cardAvailable = $connection ? $payments->supportsCard($connection) : false; } catch (\Throwable) { $connection = null; }
        }
        $requestedMethod = (string)($_POST['payment_method'] ?? 'pix');
        if ($deposit > 0) {
            if ($requestedMethod === 'card' && !$cardAvailable) HttpException::abort(422, 'Pagamento por cartão ainda não está disponível nesta Arena.');
            if (!in_array($requestedMethod, ['pix','card'], true)) $requestedMethod = 'pix';
            if ($requestedMethod === 'pix' && !$connection && empty($settings['pix_key'])) HttpException::abort(422, 'A Arena ainda não configurou uma forma de receber o sinal.');
            if ($requestedMethod === 'pix' && $connection && $email === '' && empty($settings['pix_key'])) HttpException::abort(422, 'Informe seu e-mail para gerar o Pix automático.');
            if ($requestedMethod === 'card' && $email === '') HttpException::abort(422, 'Informe seu e-mail para o pagamento por cartão.');
        } else $requestedMethod = 'onsite';

        try {
            $reservation = (new ArenaReservationService())->create(
                $tenantId,$court,$modality,$start,$duration,
                ['name'=>$name,'phone'=>$phone,'email'=>$email],
                'public',trim((string)($_POST['notes']??''))?:null,null,null,$deposit,$requestedMethod,
                $deposit>0?'pending_payment':'confirmed',$offer?(int)$offer['id']:null
            );
        } catch (\DomainException $e) { HttpException::abort(409, $e->getMessage()); }
        if (!empty($_POST['operational_reminders_consent']) && !empty($reservation['customer_id'])) {
            $pdo->prepare("INSERT INTO customer_consents(tenant_id,customer_id,type,granted,version,source,ip_address,created_at) VALUES(:tenant,:customer,'operational_reminders',1,'1.0','arena_public',:ip,NOW())")
                ->execute(['tenant'=>$tenantId,'customer'=>(int)$reservation['customer_id'],'ip'=>$_SERVER['REMOTE_ADDR']??null]);
        }
        $reservationId=(int)$reservation['id']; $rawToken=(string)$reservation['manage_token'];
        $expiresAt=$deposit>0?(new \DateTimeImmutable('+'.max(1,(int)$arenaSettings['payment_deadline_minutes']).' minutes'))->format('Y-m-d H:i:s'):null;
        $pdo->prepare('UPDATE sports_reservation_finance SET expires_at=:expires,updated_at=NOW() WHERE reservation_id=:reservation AND tenant_id=:tenant')
            ->execute(['expires'=>$expiresAt,'reservation'=>$reservationId,'tenant'=>$tenantId]);

        if ($offer) {
            $pdo->prepare("UPDATE sports_waitlist SET status='converted',converted_reservation_id=:reservation,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant AND status='offered'")
                ->execute(['reservation'=>$reservationId,'id'=>$offer['id'],'tenant'=>$tenantId]);
        }
        if ($deposit > 0 && $requestedMethod === 'pix' && $connection && $email !== '') {
            try {
                $tx=$payments->createPix($tenantId,'reservation',$reservationId,$deposit,$email,(int)$arenaSettings['payment_deadline_minutes']);
                $pdo->prepare("UPDATE sports_reservation_finance SET provider='mercadopago',external_reference=:external,transaction_id=:transaction,expires_at=:expires,updated_at=NOW() WHERE reservation_id=:reservation AND tenant_id=:tenant")
                    ->execute(['external'=>$tx['external_reference']??null,'transaction'=>$tx['provider_transaction_id']??null,'expires'=>$tx['expires_at']??$expiresAt,'reservation'=>$reservationId,'tenant'=>$tenantId]);
            } catch (\Throwable $e) { error_log('[ApPlanner Arena] Falha no Pix automático da reserva '.$reservationId.': '.$e->getMessage()); }
        }
        header('Location: /arena/reserva/'.$rawToken); exit;
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
        $cardConfig = null;
        if ($reservation['status']==='pending_payment' && ($reservation['payment_method']??'')==='card') {
            try { $cardConfig=(new TenantPaymentService())->publicCardConfig((int)$reservation['tenant_id']); } catch (\Throwable) { $cardConfig=null; }
        }
        View::render('public/sports-manage', [
            'title' => 'Sua reserva', 'reservation' => $reservation, 'settings' => $settings,
            'finance' => $financeRow, 'transaction' => $transaction, 'token' => $token, 'cardConfig'=>$cardConfig, 'publicLayout' => true,
        ]);
    }

    public function cardPayment(string $token): void
    {
        CSRF::enforce();
        $pdo=Database::connection(); $reservation=$this->reservation($pdo,$token);
        if ($reservation['status']!=='pending_payment' || ($reservation['payment_method']??'')!=='card') { $this->json(['ok'=>false,'message'=>'Esta reserva não está aguardando cartão.'],409); return; }
        $raw=file_get_contents('php://input')?:''; $payload=json_decode($raw,true);
        if(!is_array($payload)) { $payload=$_POST; }
        try {
            $tx=(new TenantPaymentService())->createCard(
                (int)$reservation['tenant_id'],'reservation',(int)$reservation['id'],(float)$reservation['deposit_amount'],
                (string)($reservation['customer_email']??''),$payload
            );
            $this->json(['ok'=>true,'status'=>$tx['status']??'pending','message'=>($tx['status']??'')==='paid'?'Pagamento aprovado. Reserva confirmada.':'Pagamento enviado para análise.']);
        } catch (\DomainException|\InvalidArgumentException $e) { $this->json(['ok'=>false,'message'=>$e->getMessage()],422); }
          catch (\Throwable $e) { error_log('[ApPlanner Arena Card] '.$e->getMessage()); $this->json(['ok'=>false,'message'=>'Não foi possível processar o cartão agora.'],502); }
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
            $pdo->prepare("UPDATE sports_reservations SET starts_at=:starts,ends_at=:ends,duration_minutes=:duration,price_per_hour=:hour,total_amount=:total,base_total_amount=:base_total,pricing_multiplier=:multiplier,pricing_details_json=:details,deposit_amount=:deposit,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['starts'=>$start->format('Y-m-d H:i:s'),'ends'=>$end->format('Y-m-d H:i:s'),'duration'=>$duration,'hour'=>$slot['price_per_hour'],'total'=>$slot['total'],'base_total'=>$slot['base_total']??$slot['total'],'multiplier'=>$slot['pricing_multiplier']??1,'details'=>json_encode($slot['pricing_adjustments']??[],JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES),'deposit'=>$newDeposit,'id'=>$current['id'],'tenant'=>$tenantId]);
            if(abs((float)($slot['total']??0)-(float)($slot['base_total']??$slot['total']))>0.009){$pdo->prepare("INSERT INTO sports_dynamic_pricing_audit(tenant_id,reservation_id,base_total,final_total,multiplier,details_json,created_at) VALUES(:tenant,:reservation,:base,:final,:multiplier,:details,NOW()) ON DUPLICATE KEY UPDATE base_total=VALUES(base_total),final_total=VALUES(final_total),multiplier=VALUES(multiplier),details_json=VALUES(details_json),created_at=NOW()")->execute(['tenant'=>$tenantId,'reservation'=>$current['id'],'base'=>$slot['base_total']??$slot['total'],'final'=>$slot['total'],'multiplier'=>$slot['pricing_multiplier']??1,'details'=>json_encode($slot['pricing_adjustments']??[],JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES)]);}
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

    private function waitlistOffer(\PDO $pdo,int $tenantId,string $token): ?array
    {
        if(!preg_match('/^[a-f0-9]{32}$/i',$token)) return null;
        $q=$pdo->prepare("SELECT * FROM sports_waitlist WHERE public_token=:token AND tenant_id=:tenant AND status='offered' AND offer_expires_at>NOW() LIMIT 1");
        $q->execute(['token'=>$token,'tenant'=>$tenantId]); $row=$q->fetch(); return $row?:null;
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
