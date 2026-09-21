<?php
namespace App\Controllers;

use App\Core\{Audit, Auth, Authorization, CSRF, Database, HttpException, TenantContext, View};
use App\Services\{ArenaMembershipService, ArenaReservationService, ArenaTournamentService, ModuleService, SportsAvailabilityService};

final class ArenaOperationsController
{
    private function access(string $permission = 'sports.view'): array
    {
        ModuleService::require('sports_courts');
        Authorization::require($permission);
        return [Database::connection(), TenantContext::id()];
    }

    public function agenda(): void
    {
        [$pdo, $tenantId] = $this->access('sports.agenda.view');
        $date = $this->date((string)($_GET['date'] ?? date('Y-m-d'))) ?: date('Y-m-d');
        $view = in_array((string)($_GET['view'] ?? 'day'), ['day', 'week'], true) ? (string)$_GET['view'] : 'day';
        $start = new \DateTimeImmutable($date . ' 00:00:00');
        if ($view === 'week') {
            $start = $start->modify('monday this week');
            $end = $start->modify('+7 days');
        } else {
            $end = $start->modify('+1 day');
        }
        $courts = $pdo->prepare("SELECT id,name FROM sports_courts WHERE tenant_id=:tenant AND active=1 ORDER BY sort_order,name");
        $courts->execute(['tenant' => $tenantId]);
        $reservations = $pdo->prepare(
            "SELECT r.*,c.name court_name,m.name modality_name
             FROM sports_reservations r
             JOIN sports_courts c ON c.id=r.court_id AND c.tenant_id=r.tenant_id
             LEFT JOIN sports_modalities m ON m.id=r.modality_id AND m.tenant_id=r.tenant_id
             WHERE r.tenant_id=:tenant AND r.starts_at<:ends AND r.ends_at>:starts
               AND r.status IN('pending_payment','confirmed','completed','no_show')
             ORDER BY r.starts_at,c.sort_order,c.name"
        );
        $reservations->execute([
            'tenant' => $tenantId,
            'starts' => $start->format('Y-m-d H:i:s'),
            'ends' => $end->format('Y-m-d H:i:s'),
        ]);
        $blocks = $pdo->prepare(
            "SELECT b.*,c.name court_name FROM sports_court_blocks b
             JOIN sports_courts c ON c.id=b.court_id AND c.tenant_id=b.tenant_id
             WHERE b.tenant_id=:tenant AND b.status='active' AND b.starts_at<:ends AND b.ends_at>:starts
             ORDER BY b.starts_at"
        );
        $blocks->execute([
            'tenant' => $tenantId,
            'starts' => $start->format('Y-m-d H:i:s'),
            'ends' => $end->format('Y-m-d H:i:s'),
        ]);
        View::render('arena/agenda', [
            'title' => 'Agenda da Arena',
            'date' => $date,
            'viewMode' => $view,
            'periodStart' => $start,
            'periodEnd' => $end,
            'courts' => $courts->fetchAll() ?: [],
            'reservations' => $reservations->fetchAll() ?: [],
            'blocks' => $blocks->fetchAll() ?: [],
        ]);
    }

    public function memberships(): void
    {
        [$pdo, $tenantId] = $this->access('sports.memberships.manage');
        $items = $pdo->prepare(
            "SELECT sm.*,c.name customer_name,sc.name court_name,m.name modality_name,
                    (SELECT COUNT(*) FROM sports_membership_conflicts cf WHERE cf.membership_id=sm.id AND cf.resolved_at IS NULL) open_conflicts,
                    (SELECT COUNT(*) FROM sports_membership_reservations mr WHERE mr.membership_id=sm.id) generated_count
             FROM sports_memberships sm
             JOIN customers c ON c.id=sm.customer_id AND c.tenant_id=sm.tenant_id
             JOIN sports_courts sc ON sc.id=sm.court_id AND sc.tenant_id=sm.tenant_id
             LEFT JOIN sports_modalities m ON m.id=sm.modality_id AND m.tenant_id=sm.tenant_id
             WHERE sm.tenant_id=:tenant ORDER BY FIELD(sm.status,'active','paused','cancelled'),sm.start_time,sm.id DESC"
        );
        $items->execute(['tenant' => $tenantId]);
        $conflicts = $pdo->prepare(
            "SELECT cf.*,sm.name membership_name,sc.name court_name FROM sports_membership_conflicts cf
             JOIN sports_memberships sm ON sm.id=cf.membership_id AND sm.tenant_id=cf.tenant_id
             JOIN sports_courts sc ON sc.id=sm.court_id
             WHERE cf.tenant_id=:tenant AND cf.resolved_at IS NULL ORDER BY cf.starts_at LIMIT 100"
        );
        $conflicts->execute(['tenant' => $tenantId]);
        View::render('arena/memberships', [
            'title' => 'Mensalistas e horários fixos',
            'memberships' => $items->fetchAll() ?: [],
            'conflicts' => $conflicts->fetchAll() ?: [],
        ] + $this->formData($pdo, $tenantId));
    }

    public function storeMembership(): void
    {
        [$pdo, $tenantId] = $this->access('sports.memberships.manage');
        CSRF::enforce();
        $customerId = (int)($_POST['customer_id'] ?? 0);
        $courtId = (int)($_POST['court_id'] ?? 0);
        $modalityId = (int)($_POST['modality_id'] ?? 0) ?: null;
        $name = trim((string)($_POST['name'] ?? ''));
        $frequency = in_array((string)($_POST['frequency'] ?? 'weekly'), ['weekly','biweekly','monthly'], true) ? (string)$_POST['frequency'] : 'weekly';
        $weekday = (int)($_POST['weekday'] ?? 0) ?: null;
        $dayOfMonth = (int)($_POST['day_of_month'] ?? 0) ?: null;
        $time = $this->time((string)($_POST['start_time'] ?? ''));
        $duration = max(15, min(1440, (int)($_POST['duration_minutes'] ?? 60)));
        $amount = $this->money($_POST['monthly_amount'] ?? null);
        $startDate = $this->date((string)($_POST['start_date'] ?? ''));
        $endDate = $this->date((string)($_POST['end_date'] ?? ''));
        if (!$customerId || !$courtId || mb_strlen($name) < 2 || !$time || !$startDate || $amount === null) {
            HttpException::abort(422, 'Revise os dados do mensalista.');
        }
        if ($frequency === 'monthly' && (!$dayOfMonth || $dayOfMonth > 31)) {
            HttpException::abort(422, 'Informe um dia do mês válido.');
        }
        if ($frequency !== 'monthly' && (!$weekday || $weekday > 7)) {
            HttpException::abort(422, 'Informe o dia da semana.');
        }
        $this->assertCustomerCourt($pdo, $tenantId, $customerId, $courtId);
        $q = $pdo->prepare(
            "INSERT INTO sports_memberships
             (tenant_id,customer_id,court_id,modality_id,name,frequency,weekday,day_of_month,start_time,duration_minutes,monthly_amount,start_date,end_date,next_generation_date,generate_days_ahead,status,notes,created_by,created_at,updated_at)
             VALUES(:tenant,:customer,:court,:modality,:name,:frequency,:weekday,:day_of_month,:time,:duration,:amount,:start_date,:end_date,:next_date,60,'active',:notes,:user,NOW(),NOW())"
        );
        $q->execute([
            'tenant' => $tenantId, 'customer' => $customerId, 'court' => $courtId, 'modality' => $modalityId,
            'name' => $name, 'frequency' => $frequency, 'weekday' => $weekday, 'day_of_month' => $dayOfMonth,
            'time' => $time, 'duration' => $duration, 'amount' => $amount, 'start_date' => $startDate,
            'end_date' => $endDate ?: null, 'next_date' => $startDate, 'notes' => trim((string)($_POST['notes'] ?? '')) ?: null,
            'user' => (int)(Auth::user()['id'] ?? 0) ?: null,
        ]);
        $id = (int)$pdo->lastInsertId();
        $result = (new ArenaMembershipService())->generate($tenantId, $id);
        $this->ensureMembershipFinance($pdo, $tenantId, $id, $amount);
        Audit::log('ARENA_MEMBERSHIP_CREATED', 'sports_memberships', $id, null, $result);
        header('Location: /sports/memberships?created=1&generated=' . (int)$result['generated'] . '&conflicts=' . (int)$result['conflicts']);
        exit;
    }

    public function generateMembershipNow(string $id): void
    {
        [, $tenantId] = $this->access('sports.memberships.manage');
        CSRF::enforce();
        $result = (new ArenaMembershipService())->generate($tenantId, (int)$id);
        Audit::log('ARENA_MEMBERSHIP_GENERATED', 'sports_memberships', (int)$id, null, $result);
        header('Location: /sports/memberships?generated=' . (int)$result['generated'] . '&conflicts=' . (int)$result['conflicts']);
        exit;
    }

    public function membershipStatus(string $id): void
    {
        [$pdo, $tenantId] = $this->access('sports.memberships.manage');
        CSRF::enforce();
        $status = (string)($_POST['status'] ?? '');
        if (!in_array($status, ['active','paused','cancelled'], true)) HttpException::abort(422, 'Status inválido.');
        $q = $pdo->prepare('UPDATE sports_memberships SET status=:status,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant');
        $q->execute(['status' => $status, 'id' => (int)$id, 'tenant' => $tenantId]);
        if (!$q->rowCount()) HttpException::abort(404, 'Mensalista não encontrado.');
        Audit::log('ARENA_MEMBERSHIP_STATUS', 'sports_memberships', (int)$id, null, ['status' => $status]);
        header('Location: /sports/memberships');
        exit;
    }

    public function games(): void
    {
        [$pdo, $tenantId] = $this->access('sports.games.manage');
        $q = $pdo->prepare(
            "SELECT g.*,c.name court_name,m.name modality_name,
                    (SELECT COUNT(*) FROM sports_game_players p WHERE p.game_id=g.id AND p.participation_status='confirmed') confirmed_players,
                    (SELECT COUNT(*) FROM sports_game_players p WHERE p.game_id=g.id AND p.payment_status='paid') paid_players,
                    (SELECT COALESCE(SUM(p.amount_paid),0) FROM sports_game_players p WHERE p.game_id=g.id) received_amount
             FROM sports_games g JOIN sports_courts c ON c.id=g.court_id AND c.tenant_id=g.tenant_id
             LEFT JOIN sports_modalities m ON m.id=g.modality_id AND m.tenant_id=g.tenant_id
             WHERE g.tenant_id=:tenant ORDER BY g.starts_at DESC LIMIT 200"
        );
        $q->execute(['tenant' => $tenantId]);
        View::render('arena/games', ['title' => 'Rachas', 'games' => $q->fetchAll() ?: []] + $this->formData($pdo, $tenantId));
    }

    public function storeGame(): void
    {
        [$pdo, $tenantId] = $this->access('sports.games.manage');
        CSRF::enforce();
        $name = trim((string)($_POST['name'] ?? ''));
        $courtId = (int)($_POST['court_id'] ?? 0);
        $modalityId = (int)($_POST['modality_id'] ?? 0);
        $players = max(2, min(100, (int)($_POST['max_players'] ?? 12)));
        $minimum = max(1, min($players, (int)($_POST['minimum_players'] ?? $players)));
        $amount = $this->money($_POST['total_amount'] ?? null);
        $duration = max(15, min(1440, (int)($_POST['duration_minutes'] ?? 120)));
        try { $start = new \DateTimeImmutable((string)($_POST['starts_at'] ?? '')); } catch (\Throwable) { $start = null; }
        if (mb_strlen($name) < 2 || !$courtId || !$modalityId || !$start || $amount === null) {
            HttpException::abort(422, 'Revise os dados do racha.');
        }
        try {
            $reservation = (new ArenaReservationService())->create(
                $tenantId, $courtId, $modalityId, $start, $duration,
                [], 'internal', 'Racha: ' . $name, null, $amount, 0, 'onsite', 'confirmed'
            );
        } catch (\DomainException $e) {
            HttpException::abort(409, $e->getMessage());
        }
        $pdo->prepare(
            "INSERT INTO sports_games
             (public_token,tenant_id,reservation_id,court_id,modality_id,name,starts_at,ends_at,total_amount,max_players,minimum_players,split_payment,status,rules,created_by,created_at,updated_at)
             VALUES(:token,:tenant,:reservation,:court,:modality,:name,:starts,:ends,:amount,:players,:minimum,:split,'open',:rules,:user,NOW(),NOW())"
        )->execute([
            'token' => bin2hex(random_bytes(16)), 'tenant' => $tenantId, 'reservation' => $reservation['id'],
            'court' => $courtId, 'modality' => $modalityId, 'name' => $name, 'starts' => $reservation['starts_at'],
            'ends' => $reservation['ends_at'], 'amount' => $amount, 'players' => $players, 'minimum' => $minimum,
            'split' => isset($_POST['split_payment']) ? 1 : 0, 'rules' => trim((string)($_POST['rules'] ?? '')) ?: null,
            'user' => (int)(Auth::user()['id'] ?? 0) ?: null,
        ]);
        $id = (int)$pdo->lastInsertId();
        Audit::log('ARENA_GAME_CREATED', 'sports_games', $id, null, ['reservation_id' => $reservation['id']]);
        header('Location: /sports/games?created=1');
        exit;
    }

    public function waitlist(): void
    {
        [$pdo, $tenantId] = $this->access('sports.waitlist.manage');
        $q = $pdo->prepare(
            "SELECT w.*,c.name court_name,m.name modality_name
             FROM sports_waitlist w LEFT JOIN sports_courts c ON c.id=w.court_id AND c.tenant_id=w.tenant_id
             LEFT JOIN sports_modalities m ON m.id=w.modality_id AND m.tenant_id=w.tenant_id
             WHERE w.tenant_id=:tenant ORDER BY FIELD(w.status,'waiting','offered','converted','expired','cancelled'),w.preferred_date,w.preferred_start,w.id DESC LIMIT 300"
        );
        $q->execute(['tenant' => $tenantId]);
        View::render('arena/waitlist', ['title' => 'Lista de espera da Arena', 'entries' => $q->fetchAll() ?: []]);
    }

    public function waitlistStatus(string $id): void
    {
        [$pdo, $tenantId] = $this->access('sports.waitlist.manage');
        CSRF::enforce();
        $status = (string)($_POST['status'] ?? '');
        if (!in_array($status, ['waiting','offered','converted','expired','cancelled'], true)) HttpException::abort(422, 'Status inválido.');
        $q = $pdo->prepare('UPDATE sports_waitlist SET status=:status,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant');
        $q->execute(['status' => $status, 'id' => (int)$id, 'tenant' => $tenantId]);
        if (!$q->rowCount()) HttpException::abort(404, 'Entrada não encontrada.');
        Audit::log('ARENA_WAITLIST_STATUS', 'sports_waitlist', (int)$id, null, ['status' => $status]);
        header('Location: /sports/waitlist');
        exit;
    }

    public function commands(): void
    {
        [$pdo, $tenantId] = $this->access('sports.commands.manage');
        $q = $pdo->prepare(
            "SELECT cmd.*,r.starts_at,r.total_amount reservation_amount,sc.name court_name,c.name customer_name,
                    (SELECT COALESCE(SUM(i.total),0) FROM sports_command_items i WHERE i.command_id=cmd.id) item_total
             FROM sports_commands cmd
             LEFT JOIN sports_reservations r ON r.id=cmd.reservation_id AND r.tenant_id=cmd.tenant_id
             LEFT JOIN sports_courts sc ON sc.id=r.court_id
             LEFT JOIN customers c ON c.id=cmd.customer_id AND c.tenant_id=cmd.tenant_id
             WHERE cmd.tenant_id=:tenant ORDER BY FIELD(cmd.status,'open','closed','cancelled'),cmd.id DESC LIMIT 200"
        );
        $q->execute(['tenant' => $tenantId]);
        $reservations = $pdo->prepare(
            "SELECT r.id,r.customer_id,r.customer_name,r.starts_at,r.total_amount,c.name court_name
             FROM sports_reservations r JOIN sports_courts c ON c.id=r.court_id
             WHERE r.tenant_id=:tenant AND r.status IN('confirmed','completed') AND r.starts_at>=DATE_SUB(NOW(),INTERVAL 1 DAY)
               AND NOT EXISTS(SELECT 1 FROM sports_commands cmd WHERE cmd.reservation_id=r.id AND cmd.status='open')
             ORDER BY r.starts_at LIMIT 200"
        );
        $reservations->execute(['tenant' => $tenantId]);
        $products = [];
        if (ModuleService::has('products', $tenantId)) {
            $pq = $pdo->prepare('SELECT id,name,sale_price,stock,cost_price FROM products WHERE tenant_id=:tenant AND active=1 ORDER BY name');
            $pq->execute(['tenant' => $tenantId]);
            $products = $pq->fetchAll() ?: [];
        }
        View::render('arena/commands', [
            'title' => 'Comandas da Arena', 'commands' => $q->fetchAll() ?: [], 'reservations' => $reservations->fetchAll() ?: [],
            'products' => $products, 'stockEnabled' => ModuleService::has('stock', $tenantId), 'financeEnabled' => ModuleService::has('finance', $tenantId),
        ]);
    }

    public function openCommand(): void
    {
        [$pdo, $tenantId] = $this->access('sports.commands.manage');
        CSRF::enforce();
        $reservationId = (int)($_POST['reservation_id'] ?? 0);
        $q = $pdo->prepare("SELECT id,customer_id FROM sports_reservations WHERE id=:id AND tenant_id=:tenant AND status IN('confirmed','completed')");
        $q->execute(['id' => $reservationId, 'tenant' => $tenantId]);
        $reservation = $q->fetch();
        if (!$reservation) HttpException::abort(422, 'Reserva inválida para comanda.');
        $pdo->prepare(
            "INSERT INTO sports_commands(public_id,tenant_id,reservation_id,customer_id,status,subtotal,discount,surcharge,total,payment_status,notes,opened_by,opened_at,updated_at)
             VALUES(:public,:tenant,:reservation,:customer,'open',0,0,0,0,'pending',:notes,:user,NOW(),NOW())"
        )->execute([
            'public' => bin2hex(random_bytes(16)), 'tenant' => $tenantId, 'reservation' => $reservationId,
            'customer' => $reservation['customer_id'] ?: null, 'notes' => trim((string)($_POST['notes'] ?? '')) ?: null,
            'user' => (int)(Auth::user()['id'] ?? 0) ?: null,
        ]);
        Audit::log('ARENA_COMMAND_OPENED', 'sports_commands', (int)$pdo->lastInsertId(), null, ['reservation_id' => $reservationId]);
        header('Location: /sports/commands?opened=1');
        exit;
    }

    public function addCommandItem(string $id): void
    {
        [$pdo,$tenantId]=$this->access('sports.commands.manage');CSRF::enforce();$commandId=(int)$id;
        $q=$pdo->prepare("SELECT id FROM sports_commands WHERE id=:id AND tenant_id=:tenant AND status='open'");$q->execute(['id'=>$commandId,'tenant'=>$tenantId]);if(!$q->fetchColumn())HttpException::abort(404,'Comanda não encontrada ou já fechada.');
        $productId=(int)($_POST['product_id']??0);$qty=$this->number($_POST['quantity']??1);if($qty<=0)HttpException::abort(422,'Quantidade inválida.');
        $description=trim((string)($_POST['description']??''));$unitPrice=$this->money($_POST['unit_price']??null);$cost=0.0;
        if($productId){if(!ModuleService::has('products',$tenantId))HttpException::abort(403,'Módulo Produtos não está ativo.');$p=$pdo->prepare('SELECT * FROM products WHERE id=:id AND tenant_id=:tenant AND active=1');$p->execute(['id'=>$productId,'tenant'=>$tenantId]);$product=$p->fetch();if(!$product)HttpException::abort(422,'Produto indisponível.');if(ModuleService::has('stock',$tenantId)&&(float)$product['stock']<$qty)HttpException::abort(409,'Estoque insuficiente.');$description=(string)$product['name'];$unitPrice=(float)$product['sale_price'];$cost=(float)$product['cost_price'];}
        else {if(mb_strlen($description)<2||$unitPrice===null)HttpException::abort(422,'Informe descrição e valor do serviço/item.');}
        $total=round((float)$unitPrice*$qty,2);$pdo->beginTransaction();try{$pdo->prepare('INSERT INTO sports_command_items(command_id,tenant_id,product_id,description,quantity,unit_price,cost_snapshot,total,created_at) VALUES(:command,:tenant,:product,:description,:qty,:price,:cost,:total,NOW())')->execute(['command'=>$commandId,'tenant'=>$tenantId,'product'=>$productId?:null,'description'=>$description,'qty'=>$qty,'price'=>$unitPrice,'cost'=>$cost,'total'=>$total]);$pdo->prepare('UPDATE sports_commands SET subtotal=(SELECT COALESCE(SUM(total),0) FROM sports_command_items WHERE command_id=:id1),total=(SELECT COALESCE(SUM(total),0) FROM sports_command_items WHERE command_id=:id2)-discount+surcharge,updated_at=NOW() WHERE id=:id3 AND tenant_id=:tenant')->execute(['id1'=>$commandId,'id2'=>$commandId,'id3'=>$commandId,'tenant'=>$tenantId]);$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
        Audit::log('ARENA_COMMAND_ITEM_ADDED','sports_commands',$commandId,null,['product_id'=>$productId?:null,'description'=>$description,'quantity'=>$qty]);header('Location: /sports/commands');exit;
    }

    public function closeCommand(string $id): void
    {
        [$pdo, $tenantId] = $this->access('sports.commands.manage');
        CSRF::enforce();
        $commandId = (int)$id;
        $discount = $this->money($_POST['discount'] ?? 0) ?? 0;
        $surcharge = $this->money($_POST['surcharge'] ?? 0) ?? 0;
        $method = (string)($_POST['payment_method'] ?? 'outro');
        if (!in_array($method, ['pix','dinheiro','credito','debito','transferencia','outro'], true)) $method='outro';
        $pdo->beginTransaction();
        try {
            $q = $pdo->prepare("SELECT * FROM sports_commands WHERE id=:id AND tenant_id=:tenant AND status='open' FOR UPDATE");
            $q->execute(['id'=>$commandId,'tenant'=>$tenantId]);
            $command = $q->fetch();
            if (!$command) throw new \DomainException('Comanda não encontrada ou já fechada.');
            $items = $pdo->prepare('SELECT i.*,p.stock,p.name product_name FROM sports_command_items i LEFT JOIN products p ON p.id=i.product_id AND p.tenant_id=i.tenant_id WHERE i.command_id=:command AND i.tenant_id=:tenant');
            $items->execute(['command'=>$commandId,'tenant'=>$tenantId]);
            $rows = $items->fetchAll() ?: [];
            $subtotal = array_sum(array_map(fn($r)=>(float)$r['total'],$rows));
            $discount = min($discount, $subtotal + $surcharge);
            $total = round(max(0, $subtotal - $discount + $surcharge),2);
            if (ModuleService::has('stock',$tenantId)) {
                $stockUsage = [];
                foreach ($rows as $item) {
                    if (empty($item['product_id'])) continue;
                    $productId = (int)$item['product_id'];
                    if (!isset($stockUsage[$productId])) $stockUsage[$productId] = ['quantity'=>0.0,'name'=>(string)$item['product_name']];
                    $stockUsage[$productId]['quantity'] += (float)$item['quantity'];
                }
                foreach ($stockUsage as $productId => $usage) {
                    $lock = $pdo->prepare('SELECT stock FROM products WHERE id=:product AND tenant_id=:tenant FOR UPDATE');
                    $lock->execute(['product'=>$productId,'tenant'=>$tenantId]);
                    $stockValue = $lock->fetchColumn();
                    if ($stockValue === false) throw new \DomainException('Produto da comanda não está mais disponível.');
                    $stock = (float)$stockValue;
                    $qty = round((float)$usage['quantity'],3);
                    if ($stock < $qty) throw new \DomainException('Estoque insuficiente para '.$usage['name'].'.');
                    $newStock = round($stock-$qty,3);
                    $pdo->prepare('UPDATE products SET stock=:stock,updated_at=NOW() WHERE id=:product AND tenant_id=:tenant')->execute(['stock'=>$newStock,'product'=>$productId,'tenant'=>$tenantId]);
                    $pdo->prepare("INSERT INTO sports_command_stock_movements(tenant_id,command_id,product_id,quantity,balance_after,movement_type,created_at) VALUES(:tenant,:command,:product,:qty,:balance,'command_close',NOW())")
                        ->execute(['tenant'=>$tenantId,'command'=>$commandId,'product'=>$productId,'qty'=>$qty,'balance'=>$newStock]);
                }
            }
            $pdo->prepare("UPDATE sports_commands SET subtotal=:subtotal,discount=:discount,surcharge=:surcharge,total=:total,payment_method=:method,payment_status='paid',status='closed',closed_by=:user,closed_at=NOW(),updated_at=NOW() WHERE id=:id AND tenant_id=:tenant")
                ->execute(['subtotal'=>$subtotal,'discount'=>$discount,'surcharge'=>$surcharge,'total'=>$total,'method'=>$method,'user'=>(int)(Auth::user()['id']??0)?:null,'id'=>$commandId,'tenant'=>$tenantId]);
            if (ModuleService::has('finance',$tenantId) && $total > 0) {
                $pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,competence_at,paid_at,created_at,updated_at) VALUES(:tenant,'arena_command',:source,'income',:description,:amount,:method,'paid',:key,CURDATE(),NOW(),NOW(),NOW())")
                    ->execute(['tenant'=>$tenantId,'source'=>$commandId,'description'=>'Comanda Arena #'.$commandId,'amount'=>$total,'method'=>$method,'key'=>'arena-command-'.$commandId]);
            }
            $pdo->commit();
        } catch (\DomainException $e) { if($pdo->inTransaction())$pdo->rollBack(); HttpException::abort(409,$e->getMessage()); }
          catch (\Throwable $e) { if($pdo->inTransaction())$pdo->rollBack(); throw $e; }
        Audit::log('ARENA_COMMAND_CLOSED', 'sports_commands', $commandId, null, ['payment_method'=>$method]);
        header('Location: /sports/commands?closed=1');
        exit;
    }

    public function reports(): void
    {
        [$pdo, $tenantId] = $this->access('sports.reports.view');
        $from = $this->date((string)($_GET['from'] ?? date('Y-m-01'))) ?: date('Y-m-01');
        $to = $this->date((string)($_GET['to'] ?? date('Y-m-d'))) ?: date('Y-m-d');
        if ($to < $from) [$from,$to]=[$to,$from];
        (new ArenaReservationService())->recalculateCustomerMetrics($tenantId);
        $summary = $pdo->prepare(
            "SELECT COUNT(*) reservations,
                    COALESCE(SUM(CASE WHEN status IN('confirmed','completed') THEN total_amount ELSE 0 END),0) revenue,
                    COALESCE(AVG(CASE WHEN status IN('confirmed','completed') THEN total_amount END),0) average_ticket,
                    SUM(status='cancelled') cancellations,SUM(status='no_show') no_shows
             FROM sports_reservations WHERE tenant_id=:tenant AND DATE(starts_at) BETWEEN :from AND :to"
        );
        $summary->execute(['tenant'=>$tenantId,'from'=>$from,'to'=>$to]);
        $courts = $pdo->prepare(
            "SELECT c.name,COUNT(r.id) reservations,COALESCE(SUM(CASE WHEN r.status IN('confirmed','completed') THEN r.total_amount ELSE 0 END),0) revenue,
                    COALESCE(SUM(CASE WHEN r.status IN('confirmed','completed','no_show') THEN TIMESTAMPDIFF(MINUTE,r.starts_at,r.ends_at) ELSE 0 END),0) occupied_minutes
             FROM sports_courts c LEFT JOIN sports_reservations r ON r.court_id=c.id AND r.tenant_id=c.tenant_id AND DATE(r.starts_at) BETWEEN :from AND :to
             WHERE c.tenant_id=:tenant GROUP BY c.id,c.name ORDER BY revenue DESC,reservations DESC"
        );
        $courts->execute(['tenant'=>$tenantId,'from'=>$from,'to'=>$to]);
        $modalities = $pdo->prepare(
            "SELECT COALESCE(m.name,'Sem modalidade') name,COUNT(r.id) reservations,COALESCE(SUM(CASE WHEN r.status IN('confirmed','completed') THEN r.total_amount ELSE 0 END),0) revenue
             FROM sports_reservations r LEFT JOIN sports_modalities m ON m.id=r.modality_id AND m.tenant_id=r.tenant_id
             WHERE r.tenant_id=:tenant AND DATE(r.starts_at) BETWEEN :from AND :to GROUP BY r.modality_id,m.name ORDER BY revenue DESC"
        );
        $modalities->execute(['tenant'=>$tenantId,'from'=>$from,'to'=>$to]);
        $crm = $pdo->prepare(
            "SELECT scm.*,c.name customer_name,sc.name favorite_court,m.name favorite_modality
             FROM sports_customer_metrics scm JOIN customers c ON c.id=scm.customer_id AND c.tenant_id=scm.tenant_id
             LEFT JOIN sports_courts sc ON sc.id=scm.favorite_court_id LEFT JOIN sports_modalities m ON m.id=scm.favorite_modality_id
             WHERE scm.tenant_id=:tenant ORDER BY FIELD(scm.segment,'vip','churn_risk','recurring','new','inactive'),scm.total_spent DESC LIMIT 100"
        );
        $crm->execute(['tenant'=>$tenantId]);
        View::render('arena/reports', [
            'title'=>'Relatórios da Arena','from'=>$from,'to'=>$to,'summary'=>$summary->fetch()?:[],
            'courtMetrics'=>$courts->fetchAll()?:[],'modalityMetrics'=>$modalities->fetchAll()?:[],'crm'=>$crm->fetchAll()?:[],
        ]);
    }

    public function classes(): void
    {
        ModuleService::require('sports_academy');[$pdo,$tenantId]=$this->access('sports.academy.manage');
        $q=$pdo->prepare("SELECT cl.*,c.name court_name,m.name modality_name,(SELECT COUNT(*) FROM sports_class_students s WHERE s.class_id=cl.id AND s.status='active') students FROM sports_classes cl JOIN sports_courts c ON c.id=cl.court_id AND c.tenant_id=cl.tenant_id LEFT JOIN sports_modalities m ON m.id=cl.modality_id AND m.tenant_id=cl.tenant_id WHERE cl.tenant_id=:tenant ORDER BY FIELD(cl.status,'active','paused','cancelled'),cl.weekday,cl.start_time");$q->execute(['tenant'=>$tenantId]);$classes=$q->fetchAll()?:[];
        $selectedId=(int)($_GET['class_id']??0);$selected=null;$students=[];$attendance=[];$makeups=[];$classDate=$this->date((string)($_GET['class_date']??date('Y-m-d')))?:date('Y-m-d');
        if($selectedId){$sq=$pdo->prepare("SELECT cl.*,c.name court_name,m.name modality_name FROM sports_classes cl JOIN sports_courts c ON c.id=cl.court_id AND c.tenant_id=cl.tenant_id LEFT JOIN sports_modalities m ON m.id=cl.modality_id AND m.tenant_id=cl.tenant_id WHERE cl.id=:id AND cl.tenant_id=:tenant");$sq->execute(['id'=>$selectedId,'tenant'=>$tenantId]);$selected=$sq->fetch()?:null;if(!$selected)HttpException::abort(404,'Turma não encontrada.');$st=$pdo->prepare("SELECT s.*,c.name customer_name,c.phone,c.email,a.status attendance_status,a.notes attendance_notes FROM sports_class_students s JOIN customers c ON c.id=s.customer_id AND c.tenant_id=s.tenant_id LEFT JOIN sports_class_attendance a ON a.student_id=s.id AND a.class_date=:date WHERE s.class_id=:class AND s.tenant_id=:tenant ORDER BY FIELD(s.status,'active','paused','cancelled'),c.name");$st->execute(['date'=>$classDate,'class'=>$selectedId,'tenant'=>$tenantId]);$students=$st->fetchAll()?:[];$mq=$pdo->prepare("SELECT mk.*,c.name student_name,rc.name replacement_class_name FROM sports_class_makeups mk JOIN sports_class_students s ON s.id=mk.student_id JOIN customers c ON c.id=s.customer_id LEFT JOIN sports_classes rc ON rc.id=mk.replacement_class_id WHERE mk.tenant_id=:tenant AND mk.original_class_id=:class ORDER BY mk.created_at DESC LIMIT 100");$mq->execute(['tenant'=>$tenantId,'class'=>$selectedId]);$makeups=$mq->fetchAll()?:[];}
        View::render('arena/classes',['title'=>'Aulas e Escolinha','classes'=>$classes,'selectedClass'=>$selected,'students'=>$students,'classDate'=>$classDate,'makeups'=>$makeups]+$this->formData($pdo,$tenantId));
    }

    public function storeClass(): void
    {
        ModuleService::require('sports_academy');[$pdo,$tenantId]=$this->access('sports.academy.manage');CSRF::enforce();$name=trim((string)($_POST['name']??''));$teacher=trim((string)($_POST['teacher_name']??''));$court=(int)($_POST['court_id']??0);$mod=(int)($_POST['modality_id']??0)?:null;$weekday=(int)($_POST['weekday']??0);$time=$this->time((string)($_POST['start_time']??''));$duration=max(15,min(240,(int)($_POST['duration_minutes']??60)));$capacity=max(1,min(200,(int)($_POST['capacity']??12)));$amount=$this->money($_POST['monthly_amount']??0)??0;if(mb_strlen($name)<2||mb_strlen($teacher)<2||!$court||$weekday<1||$weekday>7||!$time)HttpException::abort(422,'Revise os dados da turma.');$this->courtForTenant($pdo,$tenantId,$court);if($mod!==null)$this->modalityForTenant($pdo,$tenantId,$mod,$court);$pdo->prepare("INSERT INTO sports_classes(tenant_id,court_id,modality_id,teacher_name,name,level,weekday,start_time,duration_minutes,capacity,monthly_amount,status,created_at,updated_at) VALUES(:tenant,:court,:modality,:teacher,:name,:level,:weekday,:time,:duration,:capacity,:amount,'active',NOW(),NOW())")->execute(['tenant'=>$tenantId,'court'=>$court,'modality'=>$mod,'teacher'=>$teacher,'name'=>$name,'level'=>trim((string)($_POST['level']??''))?:null,'weekday'=>$weekday,'time'=>$time,'duration'=>$duration,'capacity'=>$capacity,'amount'=>$amount]);Audit::log('ARENA_CLASS_CREATED','sports_classes',(int)$pdo->lastInsertId());header('Location: /sports/classes?created=1');exit;
    }

    public function addClassStudent(string $id): void
    {
        ModuleService::require('sports_academy');[$pdo,$tenantId]=$this->access('sports.academy.manage');CSRF::enforce();$classId=(int)$id;$customer=(int)($_POST['customer_id']??0);$billingDay=(int)($_POST['billing_day']??1);$override=$this->money($_POST['monthly_amount_override']??null);$cq=$pdo->prepare("SELECT capacity,(SELECT COUNT(*) FROM sports_class_students s WHERE s.class_id=cl.id AND s.status='active') enrolled FROM sports_classes cl WHERE cl.id=:id AND cl.tenant_id=:tenant AND cl.status<>'cancelled'");$cq->execute(['id'=>$classId,'tenant'=>$tenantId]);$cl=$cq->fetch();if(!$cl)HttpException::abort(404,'Turma não encontrada.');if((int)$cl['enrolled']>=(int)$cl['capacity'])HttpException::abort(409,'A turma atingiu a capacidade máxima.');$cust=$pdo->prepare("SELECT id FROM customers WHERE id=:id AND tenant_id=:tenant AND status='active'");$cust->execute(['id'=>$customer,'tenant'=>$tenantId]);if(!$cust->fetchColumn())HttpException::abort(422,'Aluno/cliente inválido.');$pdo->prepare("INSERT INTO sports_class_students(tenant_id,class_id,customer_id,responsible_name,responsible_phone,monthly_amount_override,billing_day,status,joined_at,created_at,updated_at) VALUES(:tenant,:class,:customer,:responsible,:phone,:amount,:billing,'active',CURDATE(),NOW(),NOW()) ON DUPLICATE KEY UPDATE responsible_name=VALUES(responsible_name),responsible_phone=VALUES(responsible_phone),monthly_amount_override=VALUES(monthly_amount_override),billing_day=VALUES(billing_day),status='active',updated_at=NOW()")->execute(['tenant'=>$tenantId,'class'=>$classId,'customer'=>$customer,'responsible'=>trim((string)($_POST['responsible_name']??''))?:null,'phone'=>preg_replace('/\D/','',(string)($_POST['responsible_phone']??''))?:null,'amount'=>$override,'billing'=>max(1,min(28,$billingDay))]);Audit::log('ARENA_CLASS_STUDENT_ADDED','sports_classes',$classId,null,['customer_id'=>$customer]);header('Location: /sports/classes?class_id='.$classId.'&student=1');exit;
    }

    public function classStudentStatus(string $student): void
    {
        ModuleService::require('sports_academy');[$pdo,$tenantId]=$this->access('sports.academy.manage');CSRF::enforce();$status=(string)($_POST['status']??'');if(!in_array($status,['active','paused','cancelled'],true))HttpException::abort(422,'Status inválido.');$q=$pdo->prepare('SELECT class_id FROM sports_class_students WHERE id=:id AND tenant_id=:tenant');$q->execute(['id'=>(int)$student,'tenant'=>$tenantId]);$classId=(int)$q->fetchColumn();if(!$classId)HttpException::abort(404,'Aluno não encontrado.');$pdo->prepare('UPDATE sports_class_students SET status=:status,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant')->execute(['status'=>$status,'id'=>(int)$student,'tenant'=>$tenantId]);header('Location: /sports/classes?class_id='.$classId);exit;
    }

    public function classAttendance(string $id): void
    {
        ModuleService::require('sports_academy');[$pdo,$tenantId]=$this->access('sports.academy.manage');CSRF::enforce();$classId=(int)$id;$date=$this->date((string)($_POST['class_date']??''));if(!$date)HttpException::abort(422,'Data inválida.');$check=$pdo->prepare('SELECT 1 FROM sports_classes WHERE id=:id AND tenant_id=:tenant');$check->execute(['id'=>$classId,'tenant'=>$tenantId]);if(!$check->fetchColumn())HttpException::abort(404,'Turma não encontrada.');$statuses=(array)($_POST['attendance']??[]);$notes=(array)($_POST['attendance_notes']??[]);$valid=['present','absent','excused','replacement'];$pdo->beginTransaction();try{foreach($statuses as $studentId=>$status){$studentId=(int)$studentId;if(!in_array($status,$valid,true))continue;$sq=$pdo->prepare('SELECT 1 FROM sports_class_students WHERE id=:student AND class_id=:class AND tenant_id=:tenant');$sq->execute(['student'=>$studentId,'class'=>$classId,'tenant'=>$tenantId]);if(!$sq->fetchColumn())continue;$pdo->prepare("INSERT INTO sports_class_attendance(tenant_id,class_id,student_id,class_date,status,notes,created_at) VALUES(:tenant,:class,:student,:date,:status,:notes,NOW()) ON DUPLICATE KEY UPDATE status=VALUES(status),notes=VALUES(notes)")->execute(['tenant'=>$tenantId,'class'=>$classId,'student'=>$studentId,'date'=>$date,'status'=>$status,'notes'=>trim((string)($notes[$studentId]??''))?:null]);if(in_array($status,['absent','excused'],true)&&isset($_POST['create_makeup'][$studentId])){$pdo->prepare("INSERT INTO sports_class_makeups(tenant_id,student_id,original_class_id,original_date,status,created_by,created_at,updated_at) SELECT :tenant,:student,:class,:date,'credit',:user,NOW(),NOW() WHERE NOT EXISTS(SELECT 1 FROM sports_class_makeups WHERE tenant_id=:tenant2 AND student_id=:student2 AND original_class_id=:class2 AND original_date=:date2 AND status<>'cancelled')")->execute(['tenant'=>$tenantId,'student'=>$studentId,'class'=>$classId,'date'=>$date,'user'=>(int)(Auth::user()['id']??0)?:null,'tenant2'=>$tenantId,'student2'=>$studentId,'class2'=>$classId,'date2'=>$date]);}}$pdo->commit();}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}Audit::log('ARENA_CLASS_ATTENDANCE','sports_classes',$classId,null,['date'=>$date]);header('Location: /sports/classes?class_id='.$classId.'&class_date='.$date.'&attendance=1');exit;
    }

    public function scheduleClassMakeup(string $makeup): void
    {
        ModuleService::require('sports_academy');[$pdo,$tenantId]=$this->access('sports.academy.manage');CSRF::enforce();$replacement=(int)($_POST['replacement_class_id']??0);$date=$this->date((string)($_POST['replacement_date']??''));if(!$replacement||!$date)HttpException::abort(422,'Informe turma e data da reposição.');$rq=$pdo->prepare('SELECT 1 FROM sports_classes WHERE id=:id AND tenant_id=:tenant AND status=\'active\'');$rq->execute(['id'=>$replacement,'tenant'=>$tenantId]);if(!$rq->fetchColumn())HttpException::abort(422,'Turma de reposição inválida.');$q=$pdo->prepare("UPDATE sports_class_makeups SET replacement_class_id=:class,replacement_date=:date,status='scheduled',updated_at=NOW() WHERE id=:id AND tenant_id=:tenant AND status='credit'");$q->execute(['class'=>$replacement,'date'=>$date,'id'=>(int)$makeup,'tenant'=>$tenantId]);if(!$q->rowCount())HttpException::abort(409,'Crédito de reposição não disponível.');header('Location: /sports/classes?makeup=scheduled');exit;
    }

    public function tournaments(): void
    {
        ModuleService::require('sports_tournaments');[$pdo,$tenantId]=$this->access('sports.tournaments.manage');$q=$pdo->prepare("SELECT t.*,m.name modality_name,(SELECT COUNT(*) FROM sports_tournament_teams tm WHERE tm.tournament_id=t.id) teams,(SELECT COUNT(*) FROM sports_tournament_matches mt WHERE mt.tournament_id=t.id) matches,(SELECT name FROM sports_tournament_teams ct WHERE ct.id=t.champion_team_id) champion_name FROM sports_tournaments t LEFT JOIN sports_modalities m ON m.id=t.modality_id AND m.tenant_id=t.tenant_id WHERE t.tenant_id=:tenant ORDER BY t.starts_on DESC,t.id DESC");$q->execute(['tenant'=>$tenantId]);View::render('arena/tournaments',['title'=>'Torneios','tournaments'=>$q->fetchAll()?:[]]+$this->formData($pdo,$tenantId));
    }

    public function storeTournament(): void
    {
        ModuleService::require('sports_tournaments');[$pdo,$tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();$name=trim((string)($_POST['name']??''));$mod=(int)($_POST['modality_id']??0)?:null;$format=in_array((string)($_POST['format']??''),['groups','knockout','groups_knockout'],true)?(string)$_POST['format']:'groups_knockout';$start=$this->date((string)($_POST['starts_on']??''));$end=$this->date((string)($_POST['ends_on']??''));$amount=$this->money($_POST['registration_amount']??0)??0;if(mb_strlen($name)<2||!$start)HttpException::abort(422,'Revise os dados do torneio.');if($end!==null&&$end<$start)HttpException::abort(422,'A data final não pode ser anterior à inicial.');if($mod!==null)$this->modalityForTenant($pdo,$tenantId,$mod,null);$pdo->prepare("INSERT INTO sports_tournaments(tenant_id,modality_id,name,category,format,registration_amount,starts_on,ends_on,status,created_at,updated_at) VALUES(:tenant,:modality,:name,:category,:format,:amount,:starts,:ends,'draft',NOW(),NOW())")->execute(['tenant'=>$tenantId,'modality'=>$mod,'name'=>$name,'category'=>trim((string)($_POST['category']??''))?:null,'format'=>$format,'amount'=>$amount,'starts'=>$start,'ends'=>$end?:null]);$id=(int)$pdo->lastInsertId();Audit::log('ARENA_TOURNAMENT_CREATED','sports_tournaments',$id);header('Location: /sports/tournaments/'.$id);exit;
    }

    public function tournamentDetail(string $id): void
    {
        ModuleService::require('sports_tournaments');[$pdo,$tenantId]=$this->access('sports.tournaments.manage');$tq=$pdo->prepare("SELECT t.*,m.name modality_name,ct.name champion_name FROM sports_tournaments t LEFT JOIN sports_modalities m ON m.id=t.modality_id AND m.tenant_id=t.tenant_id LEFT JOIN sports_tournament_teams ct ON ct.id=t.champion_team_id WHERE t.id=:id AND t.tenant_id=:tenant");$tq->execute(['id'=>(int)$id,'tenant'=>$tenantId]);$t=$tq->fetch();if(!$t)HttpException::abort(404,'Torneio não encontrado.');$teams=$pdo->prepare("SELECT tm.*,c.name captain_name,(SELECT COUNT(*) FROM sports_tournament_team_players p WHERE p.team_id=tm.id) players FROM sports_tournament_teams tm LEFT JOIN customers c ON c.id=tm.captain_customer_id AND c.tenant_id=tm.tenant_id WHERE tm.tournament_id=:id AND tm.tenant_id=:tenant ORDER BY tm.group_name,tm.name");$teams->execute(['id'=>$t['id'],'tenant'=>$tenantId]);$matches=$pdo->prepare("SELECT mt.*,hc.name home_name,ac.name away_name,c.name court_name FROM sports_tournament_matches mt LEFT JOIN sports_tournament_teams hc ON hc.id=mt.home_team_id LEFT JOIN sports_tournament_teams ac ON ac.id=mt.away_team_id LEFT JOIN sports_courts c ON c.id=mt.court_id AND c.tenant_id=mt.tenant_id WHERE mt.tournament_id=:id AND mt.tenant_id=:tenant ORDER BY COALESCE(mt.starts_at,'9999-12-31'),mt.round_number,mt.id");$matches->execute(['id'=>$t['id'],'tenant'=>$tenantId]);$players=$pdo->prepare("SELECT p.team_id,p.customer_id,p.jersey_number,c.name FROM sports_tournament_team_players p JOIN customers c ON c.id=p.customer_id AND c.tenant_id=p.tenant_id JOIN sports_tournament_teams tm ON tm.id=p.team_id WHERE tm.tournament_id=:id AND p.tenant_id=:tenant ORDER BY c.name");$players->execute(['id'=>$t['id'],'tenant'=>$tenantId]);$byTeam=[];foreach($players->fetchAll() as $p)$byTeam[(int)$p['team_id']][]=$p;$stand=(new ArenaTournamentService())->standings($tenantId,(int)$t['id']);View::render('arena/tournament-detail',['title'=>$t['name'],'tournament'=>$t,'teams'=>$teams->fetchAll()?:[],'matches'=>$matches->fetchAll()?:[],'playersByTeam'=>$byTeam,'standings'=>$stand]+$this->formData($pdo,$tenantId));
    }

    public function tournamentAddTeam(string $id): void
    {
        ModuleService::require('sports_tournaments');[$pdo,$tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();$name=trim((string)($_POST['name']??''));$captain=(int)($_POST['captain_customer_id']??0)?:null;if(mb_strlen($name)<2)HttpException::abort(422,'Informe o nome da equipe.');$t=$pdo->prepare('SELECT status FROM sports_tournaments WHERE id=:id AND tenant_id=:tenant');$t->execute(['id'=>(int)$id,'tenant'=>$tenantId]);if($t->fetchColumn()===false)HttpException::abort(404,'Torneio não encontrado.');if($captain){$c=$pdo->prepare('SELECT 1 FROM customers WHERE id=:id AND tenant_id=:tenant');$c->execute(['id'=>$captain,'tenant'=>$tenantId]);if(!$c->fetchColumn())HttpException::abort(422,'Capitão inválido.');}$pdo->prepare("INSERT INTO sports_tournament_teams(tournament_id,tenant_id,name,captain_customer_id,payment_status,amount_paid,created_at) VALUES(:tournament,:tenant,:name,:captain,'pending',0,NOW())")->execute(['tournament'=>(int)$id,'tenant'=>$tenantId,'name'=>$name,'captain'=>$captain]);header('Location: /sports/tournaments/'.(int)$id.'?team=1');exit;
    }

    public function tournamentAddPlayer(string $id,string $team): void
    {
        ModuleService::require('sports_tournaments');[$pdo,$tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();$customer=(int)($_POST['customer_id']??0);$jersey=(int)($_POST['jersey_number']??0)?:null;$q=$pdo->prepare('SELECT 1 FROM sports_tournament_teams WHERE id=:team AND tournament_id=:tournament AND tenant_id=:tenant');$q->execute(['team'=>(int)$team,'tournament'=>(int)$id,'tenant'=>$tenantId]);if(!$q->fetchColumn())HttpException::abort(404,'Equipe inválida.');$c=$pdo->prepare('SELECT 1 FROM customers WHERE id=:id AND tenant_id=:tenant');$c->execute(['id'=>$customer,'tenant'=>$tenantId]);if(!$c->fetchColumn())HttpException::abort(422,'Jogador inválido.');$pdo->prepare("INSERT INTO sports_tournament_team_players(team_id,customer_id,tenant_id,jersey_number,created_at) VALUES(:team,:customer,:tenant,:jersey,NOW()) ON DUPLICATE KEY UPDATE jersey_number=VALUES(jersey_number)")->execute(['team'=>(int)$team,'customer'=>$customer,'tenant'=>$tenantId,'jersey'=>$jersey]);header('Location: /sports/tournaments/'.(int)$id.'?player=1');exit;
    }

    public function tournamentGenerate(string $id): void
    {
        ModuleService::require('sports_tournaments');[, $tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();try{$r=(new ArenaTournamentService())->generateFixtures($tenantId,(int)$id);}catch(\DomainException $e){HttpException::abort(409,$e->getMessage());}Audit::log('ARENA_TOURNAMENT_FIXTURES','sports_tournaments',(int)$id,null,$r);header('Location: /sports/tournaments/'.(int)$id.'?fixtures=1');exit;
    }

    public function tournamentScheduleMatch(string $id,string $match): void
    {
        ModuleService::require('sports_tournaments');[, $tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();$court=(int)($_POST['court_id']??0);$duration=max(15,min(300,(int)($_POST['duration_minutes']??60)));try{$start=new \DateTimeImmutable((string)($_POST['starts_at']??''));$reservation=(new ArenaTournamentService())->scheduleMatch($tenantId,(int)$match,$court,$start,$duration);}catch(\DomainException|\InvalidArgumentException $e){HttpException::abort(409,$e->getMessage());}catch(\Throwable){HttpException::abort(422,'Data/horário inválidos.');}Audit::log('ARENA_TOURNAMENT_MATCH_SCHEDULED','sports_tournament_matches',(int)$match,null,['reservation_id'=>$reservation]);header('Location: /sports/tournaments/'.(int)$id.'?scheduled=1');exit;
    }

    public function tournamentScore(string $id,string $match): void
    {
        ModuleService::require('sports_tournaments');[, $tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();try{(new ArenaTournamentService())->score($tenantId,(int)$match,max(0,(int)($_POST['home_score']??0)),max(0,(int)($_POST['away_score']??0)));}catch(\DomainException|\InvalidArgumentException $e){HttpException::abort(422,$e->getMessage());}header('Location: /sports/tournaments/'.(int)$id.'?score=1');exit;
    }

    public function tournamentAdvance(string $id): void
    {
        ModuleService::require('sports_tournaments');[, $tenantId]=$this->access('sports.tournaments.manage');CSRF::enforce();try{$r=(new ArenaTournamentService())->advance($tenantId,(int)$id);}catch(\DomainException $e){HttpException::abort(409,$e->getMessage());}Audit::log('ARENA_TOURNAMENT_ADVANCED','sports_tournaments',(int)$id,null,$r);header('Location: /sports/tournaments/'.(int)$id.'?advanced=1');exit;
    }

    public function settings(): void
    {
        [$pdo, $tenantId] = $this->access('sports.manage');
        $q = $pdo->prepare('SELECT * FROM sports_arena_settings WHERE tenant_id=:tenant');
        $q->execute(['tenant' => $tenantId]);
        $settings = $q->fetch() ?: [
            'payment_deadline_minutes'=>10,'waitlist_offer_minutes'=>10,'allow_waitlist'=>1,'allow_games'=>1,
            'dynamic_pricing_enabled'=>0,'dynamic_min_multiplier'=>0.80,'dynamic_max_multiplier'=>1.30,
            'dynamic_last_minute_hours'=>4,'dynamic_last_minute_discount_percent'=>10,
            'dynamic_high_occupancy_threshold'=>70,'dynamic_high_occupancy_surcharge_percent'=>10,
            'dynamic_low_occupancy_threshold'=>30,'dynamic_low_occupancy_discount_percent'=>5,
            'dynamic_low_demand_window_hours'=>24,'dynamic_weekend_surcharge_percent'=>0,'dynamic_rounding_step'=>0.01,
            'waitlist_email_enabled'=>1,'waitlist_whatsapp_enabled'=>0,'reservation_reminder_enabled'=>1,
            'reservation_reminder_hours'=>24,'crm_return_enabled'=>0,'crm_return_days'=>30,'idle_slot_campaign_enabled'=>0,
            'idle_slot_hours_before'=>24,'amenities_json'=>null,'public_rules'=>null,'cancellation_policy'=>null,
        ];
        $settings['amenities'] = json_decode((string)($settings['amenities_json'] ?? '[]'), true) ?: [];
        View::render('arena/settings', [
            'title' => 'Configurações da Arena',
            'settings' => $settings,
            'bankingEnabled' => ModuleService::has('banking_integrations', $tenantId),
        ]);
    }

    public function saveSettings(): void
    {
        [$pdo, $tenantId] = $this->access('sports.manage');
        CSRF::enforce();
        $allowedAmenities=['parking','locker_room','shower','bar','restaurant','wifi','stands','bbq','equipment_rental','accessibility'];
        $amenities=array_values(array_intersect($allowedAmenities,(array)($_POST['amenities']??[])));
        $deadline=max(1,min(1440,(int)($_POST['payment_deadline_minutes']??10)));
        $offer=max(1,min(1440,(int)($_POST['waitlist_offer_minutes']??10)));
        $dynamic=isset($_POST['dynamic_pricing_enabled'])?1:0;
        $minMultiplier=max(0.10,min(2.00,(float)str_replace(',','.',(string)($_POST['dynamic_min_multiplier']??'0.80'))));
        $maxMultiplier=max($minMultiplier,min(5.00,(float)str_replace(',','.',(string)($_POST['dynamic_max_multiplier']??'1.30'))));
        $lastHours=max(0,min(168,(int)($_POST['dynamic_last_minute_hours']??4)));
        $lastDiscount=max(0,min(90,(float)str_replace(',','.',(string)($_POST['dynamic_last_minute_discount_percent']??10))));
        $highThreshold=max(0,min(100,(float)str_replace(',','.',(string)($_POST['dynamic_high_occupancy_threshold']??70))));
        $highSurcharge=max(0,min(200,(float)str_replace(',','.',(string)($_POST['dynamic_high_occupancy_surcharge_percent']??10))));
        $lowThreshold=max(0,min(100,(float)str_replace(',','.',(string)($_POST['dynamic_low_occupancy_threshold']??30))));
        $lowDiscount=max(0,min(90,(float)str_replace(',','.',(string)($_POST['dynamic_low_occupancy_discount_percent']??5))));
        $lowWindow=max(0,min(720,(int)($_POST['dynamic_low_demand_window_hours']??24)));
        $weekend=max(0,min(200,(float)str_replace(',','.',(string)($_POST['dynamic_weekend_surcharge_percent']??0))));
        $rounding=max(0.01,min(100,(float)str_replace(',','.',(string)($_POST['dynamic_rounding_step']??'0.01'))));
        $reminderHours=max(1,min(336,(int)($_POST['reservation_reminder_hours']??24)));
        $returnDays=max(7,min(365,(int)($_POST['crm_return_days']??30)));
        $idleHours=max(1,min(336,(int)($_POST['idle_slot_hours_before']??24)));
        $pdo->prepare(
            "INSERT INTO sports_arena_settings
             (tenant_id,payment_deadline_minutes,waitlist_offer_minutes,allow_waitlist,waitlist_email_enabled,waitlist_whatsapp_enabled,allow_games,
              reservation_reminder_enabled,reservation_reminder_hours,crm_return_enabled,crm_return_days,idle_slot_campaign_enabled,idle_slot_hours_before,
              dynamic_pricing_enabled,dynamic_min_multiplier,dynamic_max_multiplier,dynamic_last_minute_hours,dynamic_last_minute_discount_percent,
              dynamic_high_occupancy_threshold,dynamic_high_occupancy_surcharge_percent,dynamic_low_occupancy_threshold,dynamic_low_occupancy_discount_percent,
              dynamic_low_demand_window_hours,dynamic_weekend_surcharge_percent,dynamic_rounding_step,amenities_json,public_rules,cancellation_policy,updated_at)
             VALUES(:tenant,:deadline,:offer,:waitlist,:wait_email,:wait_wa,:games,:reminder,:reminder_hours,:crm_return,:return_days,:idle,:idle_hours,
              :dynamic,:min_multiplier,:max_multiplier,:last_hours,:last_discount,:high_threshold,:high_surcharge,:low_threshold,:low_discount,:low_window,
              :weekend,:rounding,:amenities,:rules,:policy,NOW())
             ON DUPLICATE KEY UPDATE payment_deadline_minutes=VALUES(payment_deadline_minutes),waitlist_offer_minutes=VALUES(waitlist_offer_minutes),
               allow_waitlist=VALUES(allow_waitlist),waitlist_email_enabled=VALUES(waitlist_email_enabled),waitlist_whatsapp_enabled=VALUES(waitlist_whatsapp_enabled),
               allow_games=VALUES(allow_games),reservation_reminder_enabled=VALUES(reservation_reminder_enabled),reservation_reminder_hours=VALUES(reservation_reminder_hours),
               crm_return_enabled=VALUES(crm_return_enabled),crm_return_days=VALUES(crm_return_days),idle_slot_campaign_enabled=VALUES(idle_slot_campaign_enabled),
               idle_slot_hours_before=VALUES(idle_slot_hours_before),dynamic_pricing_enabled=VALUES(dynamic_pricing_enabled),dynamic_min_multiplier=VALUES(dynamic_min_multiplier),
               dynamic_max_multiplier=VALUES(dynamic_max_multiplier),dynamic_last_minute_hours=VALUES(dynamic_last_minute_hours),
               dynamic_last_minute_discount_percent=VALUES(dynamic_last_minute_discount_percent),dynamic_high_occupancy_threshold=VALUES(dynamic_high_occupancy_threshold),
               dynamic_high_occupancy_surcharge_percent=VALUES(dynamic_high_occupancy_surcharge_percent),dynamic_low_occupancy_threshold=VALUES(dynamic_low_occupancy_threshold),
               dynamic_low_occupancy_discount_percent=VALUES(dynamic_low_occupancy_discount_percent),dynamic_low_demand_window_hours=VALUES(dynamic_low_demand_window_hours),
               dynamic_weekend_surcharge_percent=VALUES(dynamic_weekend_surcharge_percent),dynamic_rounding_step=VALUES(dynamic_rounding_step),
               amenities_json=VALUES(amenities_json),public_rules=VALUES(public_rules),cancellation_policy=VALUES(cancellation_policy),updated_at=NOW()"
        )->execute([
            'tenant'=>$tenantId,'deadline'=>$deadline,'offer'=>$offer,'waitlist'=>isset($_POST['allow_waitlist'])?1:0,
            'wait_email'=>isset($_POST['waitlist_email_enabled'])?1:0,'wait_wa'=>isset($_POST['waitlist_whatsapp_enabled'])?1:0,
            'games'=>isset($_POST['allow_games'])?1:0,'reminder'=>isset($_POST['reservation_reminder_enabled'])?1:0,'reminder_hours'=>$reminderHours,
            'crm_return'=>isset($_POST['crm_return_enabled'])?1:0,'return_days'=>$returnDays,'idle'=>isset($_POST['idle_slot_campaign_enabled'])?1:0,'idle_hours'=>$idleHours,
            'dynamic'=>$dynamic,'min_multiplier'=>$minMultiplier,'max_multiplier'=>$maxMultiplier,'last_hours'=>$lastHours,'last_discount'=>$lastDiscount,
            'high_threshold'=>$highThreshold,'high_surcharge'=>$highSurcharge,'low_threshold'=>$lowThreshold,'low_discount'=>$lowDiscount,'low_window'=>$lowWindow,
            'weekend'=>$weekend,'rounding'=>$rounding,
            'amenities'=>json_encode($amenities,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR),
            'rules'=>trim((string)($_POST['public_rules']??''))?:null,'policy'=>trim((string)($_POST['cancellation_policy']??''))?:null,
        ]);
        Audit::log('ARENA_SETTINGS_UPDATED','sports_arena_settings',$tenantId,null,[
            'dynamic_pricing_enabled'=>(bool)$dynamic,'dynamic_min_multiplier'=>$minMultiplier,'dynamic_max_multiplier'=>$maxMultiplier,
            'payment_deadline_minutes'=>$deadline,'waitlist_offer_minutes'=>$offer,'amenities'=>$amenities
        ]);
        header('Location: /sports/arena-settings?saved=1');exit;
    }

    private function generateMembership(int $membershipId, int $tenantId): array
    {
        $pdo = Database::connection();
        $q = $pdo->prepare("SELECT sm.*,c.name customer_name,c.phone customer_phone,c.email customer_email FROM sports_memberships sm JOIN customers c ON c.id=sm.customer_id AND c.tenant_id=sm.tenant_id WHERE sm.id=:id AND sm.tenant_id=:tenant AND sm.status='active'");
        $q->execute(['id'=>$membershipId,'tenant'=>$tenantId]);$m=$q->fetch();if(!$m)throw new \DomainException('Mensalista ativo não encontrado.');
        $from = new \DateTimeImmutable(max(date('Y-m-d'), (string)$m['start_date']) . ' 00:00:00');
        $to = $from->modify('+' . (int)$m['generate_days_ahead'] . ' days');
        if(!empty($m['end_date'])){$limit=new \DateTimeImmutable($m['end_date'].' 23:59:59');if($limit<$to)$to=$limit;}
        $generated=0;$conflicts=0;$service=new ArenaReservationService();
        for($d=$from;$d<=$to;$d=$d->modify('+1 day')){
            if(!$this->membershipOccurs($m,$d))continue;$date=$d->format('Y-m-d');
            $exists=$pdo->prepare('SELECT 1 FROM sports_membership_reservations WHERE membership_id=:membership AND occurrence_date=:date');$exists->execute(['membership'=>$membershipId,'date'=>$date]);if($exists->fetchColumn())continue;
            $start=new \DateTimeImmutable($date.' '.$m['start_time']);
            try{
                $reservation=$service->create($tenantId,(int)$m['court_id'],(int)($m['modality_id']??0),$start,(int)$m['duration_minutes'],['id'=>(int)$m['customer_id'],'name'=>$m['customer_name'],'phone'=>$m['customer_phone'],'email'=>$m['customer_email']],'recurring','Mensalista #'.$membershipId,substr(hash('md5','membership-'.$membershipId),0,32));
                $pdo->prepare('INSERT INTO sports_membership_reservations(membership_id,reservation_id,tenant_id,occurrence_date,created_at) VALUES(:membership,:reservation,:tenant,:date,NOW())')->execute(['membership'=>$membershipId,'reservation'=>$reservation['id'],'tenant'=>$tenantId,'date'=>$date]);$generated++;
            }catch(\DomainException $e){$pdo->prepare("INSERT INTO sports_membership_conflicts(membership_id,tenant_id,occurrence_date,starts_at,reason,created_at) VALUES(:membership,:tenant,:date,:starts,:reason,NOW()) ON DUPLICATE KEY UPDATE reason=VALUES(reason)")->execute(['membership'=>$membershipId,'tenant'=>$tenantId,'date'=>$date,'starts'=>$start->format('Y-m-d H:i:s'),'reason'=>mb_substr($e->getMessage(),0,300)]);$conflicts++;}
        }
        $pdo->prepare('UPDATE sports_memberships SET next_generation_date=:next,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant')->execute(['next'=>$to->modify('+1 day')->format('Y-m-d'),'id'=>$membershipId,'tenant'=>$tenantId]);
        return ['generated'=>$generated,'conflicts'=>$conflicts];
    }

    private function membershipOccurs(array $m, \DateTimeImmutable $date): bool
    {
        $start = new \DateTimeImmutable($m['start_date'].' 00:00:00');
        if($date<$start)return false;if(!empty($m['end_date'])&&$date>new \DateTimeImmutable($m['end_date'].' 23:59:59'))return false;
        if($m['frequency']==='monthly')return (int)$date->format('j')===(int)$m['day_of_month'];
        if((int)$date->format('N')!==(int)$m['weekday'])return false;
        $anchor=$start;while((int)$anchor->format('N')!==(int)$m['weekday'])$anchor=$anchor->modify('+1 day');if($date<$anchor)return false;
        $days=(int)$anchor->diff($date)->format('%a');$interval=$m['frequency']==='biweekly'?14:7;return $days%$interval===0;
    }

    private function ensureMembershipFinance(\PDO $pdo,int $tenantId,int $membershipId,float $amount):void
    {
        if(!ModuleService::has('finance',$tenantId)||$amount<=0)return;$key='arena-membership-'.$membershipId.'-'.date('Ym');
        $pdo->prepare("INSERT IGNORE INTO financial_transactions(tenant_id,source_type,source_id,type,description,amount,payment_method,status,idempotency_key,due_at,competence_at,created_at,updated_at) VALUES(:tenant,'arena_membership',:source,'income',:description,:amount,'outro','pending',:key,CURDATE(),CURDATE(),NOW(),NOW())")
            ->execute(['tenant'=>$tenantId,'source'=>$membershipId,'description'=>'Mensalidade Arena #'.$membershipId,'amount'=>$amount,'key'=>$key]);
    }

    private function formData(\PDO $pdo,int $tenantId):array
    {
        $c=$pdo->prepare("SELECT id,name,phone,email FROM customers WHERE tenant_id=:tenant AND status='active' ORDER BY name LIMIT 1000");$c->execute(['tenant'=>$tenantId]);
        $courts=$pdo->prepare("SELECT id,name FROM sports_courts WHERE tenant_id=:tenant AND active=1 ORDER BY sort_order,name");$courts->execute(['tenant'=>$tenantId]);
        $mods=$pdo->prepare("SELECT id,name FROM sports_modalities WHERE tenant_id=:tenant AND active=1 ORDER BY sort_order,name");$mods->execute(['tenant'=>$tenantId]);
        return ['customers'=>$c->fetchAll()?:[],'courts'=>$courts->fetchAll()?:[],'modalities'=>$mods->fetchAll()?:[]];
    }

    private function courtForTenant(\PDO $pdo,int $tenantId,int $courtId):void
    {
        $q=$pdo->prepare("SELECT 1 FROM sports_courts WHERE id=:court AND tenant_id=:tenant AND active=1");
        $q->execute(['court'=>$courtId,'tenant'=>$tenantId]);
        if(!$q->fetchColumn())HttpException::abort(422,'Quadra inválida para esta Arena.');
    }
    private function modalityForTenant(\PDO $pdo,int $tenantId,int $modalityId,?int $courtId=null):void
    {
        $sql=$courtId===null
            ? "SELECT 1 FROM sports_modalities WHERE id=:modality AND tenant_id=:tenant AND active=1"
            : "SELECT 1 FROM sports_modalities m JOIN sports_court_modalities cm ON cm.modality_id=m.id WHERE m.id=:modality AND m.tenant_id=:tenant AND m.active=1 AND cm.court_id=:court";
        $params=['modality'=>$modalityId,'tenant'=>$tenantId];if($courtId!==null)$params['court']=$courtId;
        $q=$pdo->prepare($sql);$q->execute($params);if(!$q->fetchColumn())HttpException::abort(422,'Modalidade inválida para esta Arena.');
    }
    private function assertCustomerCourt(\PDO $pdo,int $tenantId,int $customerId,int $courtId):void
    {
        $q=$pdo->prepare("SELECT (SELECT COUNT(*) FROM customers WHERE id=:customer AND tenant_id=:tenant AND status='active') customer_ok,(SELECT COUNT(*) FROM sports_courts WHERE id=:court AND tenant_id=:tenant2 AND active=1) court_ok");$q->execute(['customer'=>$customerId,'tenant'=>$tenantId,'court'=>$courtId,'tenant2'=>$tenantId]);$r=$q->fetch();if(!$r||!(int)$r['customer_ok']||!(int)$r['court_ok'])HttpException::abort(422,'Cliente ou quadra inválidos.');
    }
    private function money(mixed $value):?float{$x=filter_var(str_replace(',','.',trim((string)$value)),FILTER_VALIDATE_FLOAT);return $x===false||$x<0?null:round((float)$x,2);}
    private function number(mixed $value):float{$x=filter_var(str_replace(',','.',trim((string)$value)),FILTER_VALIDATE_FLOAT);return $x===false?0:(float)$x;}
    private function date(string $value):?string{if($value==='')return null;if(!preg_match('/^\d{4}-\d{2}-\d{2}$/',$value))return null;$d=\DateTimeImmutable::createFromFormat('!Y-m-d',$value);return $d&&$d->format('Y-m-d')===$value?$value:null;}
    private function time(string $value):?string{if(!preg_match('/^(\d{2}):(\d{2})(?::(\d{2}))?$/',$value,$m))return null;$h=(int)$m[1];$i=(int)$m[2];$s=(int)($m[3]??0);return $h<24&&$i<60&&$s<60?sprintf('%02d:%02d:%02d',$h,$i,$s):null;}
}
