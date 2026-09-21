<?php
namespace App\Controllers;

use App\Core\{CSRF,Database,HttpException,RateLimiter,View};
use App\Services\{ModuleService,TenantPaymentService};

final class PublicArenaExtrasController
{
    public function game(string $token): void
    {
        $pdo = Database::connection();
        $game = $this->gameRow($pdo, $token);
        $players = $pdo->prepare(
            "SELECT name,participation_status,payment_status,share_amount,amount_paid,confirmed_at
             FROM sports_game_players WHERE game_id=:game AND participation_status<>'cancelled' ORDER BY id"
        );
        $players->execute(['game' => $game['id']]);
        $player = null;
        $private = trim((string)($_GET['participante'] ?? ''));
        if ($private !== '' && preg_match('/^[a-f0-9]{64}$/i', $private)) {
            $q = $pdo->prepare('SELECT * FROM sports_game_players WHERE game_id=:game AND manage_token_hash=:token LIMIT 1');
            $q->execute(['game' => $game['id'], 'token' => hash('sha256', $private)]);
            $player = $q->fetch() ?: null;
            if ($player) {
                $tx = $pdo->prepare("SELECT * FROM tenant_payment_transactions WHERE tenant_id=:tenant AND reference_type='game_player' AND reference_id=:id ORDER BY id DESC LIMIT 1");
                $tx->execute(['tenant' => $game['tenant_id'], 'id' => $player['id']]);
                $player['transaction'] = $tx->fetch() ?: null;
            }
        }
        $count = $pdo->prepare("SELECT COUNT(*) FROM sports_game_players WHERE game_id=:game AND participation_status='confirmed'");
        $count->execute(['game' => $game['id']]);
        $confirmed = (int)$count->fetchColumn();
        View::render('public/arena-game', [
            'title' => $game['name'] . ' · ' . $game['tenant_name'],
            'publicLayout' => true,
            'game' => $game,
            'players' => $players->fetchAll() ?: [],
            'confirmed' => $confirmed,
            'available' => max(0, (int)$game['max_players'] - $confirmed),
            'privateToken' => $private,
            'player' => $player,
        ]);
    }

    public function joinGame(string $token): void
    {
        CSRF::enforce();
        $ip = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
        if (!RateLimiter::hit('arena-game-join|' . $ip, 12, 3600)) HttpException::abort(429, 'Muitas tentativas. Aguarde alguns minutos.');

        $name = trim((string)($_POST['name'] ?? ''));
        $phone = preg_replace('/\D/', '', (string)($_POST['phone'] ?? ''));
        $email = mb_strtolower(trim((string)($_POST['email'] ?? '')));
        if (mb_strlen($name) < 2 || strlen($phone) < 10 || ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) || !isset($_POST['terms'])) {
            HttpException::abort(422, 'Revise seus dados e aceite as condições do racha.');
        }

        $pdo = Database::connection();
        $pdo->beginTransaction();
        $private = bin2hex(random_bytes(32));
        try {
            $q = $pdo->prepare(
                "SELECT g.*,t.name tenant_name FROM sports_games g JOIN tenants t ON t.id=g.tenant_id
                 WHERE g.public_token=:token AND g.status IN('open','confirmed') FOR UPDATE"
            );
            $q->execute(['token' => $token]);
            $game = $q->fetch();
            if (!$game) throw new \DomainException('Este racha não está aberto para inscrições.');
            if (new \DateTimeImmutable($game['starts_at']) <= new \DateTimeImmutable()) throw new \DomainException('As inscrições deste racha foram encerradas.');

            $count = $pdo->prepare("SELECT COUNT(*) FROM sports_game_players WHERE game_id=:game AND participation_status='confirmed'");
            $count->execute(['game' => $game['id']]);
            $confirmedBefore = (int)$count->fetchColumn();
            if ($confirmedBefore >= (int)$game['max_players']) throw new \DomainException('As vagas deste racha foram preenchidas.');

            $dup = $pdo->prepare("SELECT id FROM sports_game_players WHERE game_id=:game AND phone=:phone AND participation_status<>'cancelled' LIMIT 1");
            $dup->execute(['game' => $game['id'], 'phone' => $phone]);
            if ($dup->fetchColumn()) throw new \DomainException('Este telefone já está inscrito no racha.');

            $customer = $this->customer($pdo, (int)$game['tenant_id'], $name, $phone, $email);
            $share = !empty($game['split_payment']) ? round((float)$game['total_amount'] / max(1, (int)$game['max_players']), 2) : 0.0;
            $ins = $pdo->prepare(
                "INSERT INTO sports_game_players
                 (game_id,tenant_id,customer_id,name,phone,email,share_amount,amount_paid,participation_status,payment_status,manage_token_hash,confirmed_at,created_at,updated_at)
                 VALUES(:game,:tenant,:customer,:name,:phone,:email,:share,0,'confirmed',:payment,:token,NOW(),NOW(),NOW())"
            );
            $ins->execute([
                'game' => $game['id'], 'tenant' => $game['tenant_id'], 'customer' => $customer, 'name' => $name,
                'phone' => $phone, 'email' => $email ?: null, 'share' => $share,
                'payment' => $share > 0 ? 'pending' : 'paid', 'token' => hash('sha256', $private),
            ]);
            $playerId = (int)$pdo->lastInsertId();
            $newCount = $confirmedBefore + 1;
            if ($newCount >= max(1, (int)$game['minimum_players'])) {
                $pdo->prepare("UPDATE sports_games SET status=IF(status='open','confirmed',status),updated_at=NOW() WHERE id=:id")->execute(['id' => $game['id']]);
            }
            $pdo->commit();
        } catch (\Throwable $e) {
            if ($pdo->inTransaction()) $pdo->rollBack();
            if ($e instanceof \DomainException) HttpException::abort(409, $e->getMessage());
            throw $e;
        }

        // Pagamento individual é tentado apenas quando o módulo independente está ativo e conectado.
        try {
            if ($share > 0 && $email !== '' && ModuleService::has('banking_integrations', (int)$game['tenant_id'])) {
                $payments = new TenantPaymentService();
                if ($payments->connected((int)$game['tenant_id'])) {
                    $tx = $payments->createPix((int)$game['tenant_id'], 'game_player', $playerId, $share, $email, 30);
                    $pdo->prepare('UPDATE sports_game_players SET provider=:provider,provider_reference=:ref,updated_at=NOW() WHERE id=:id AND tenant_id=:tenant')
                        ->execute(['provider' => 'mercadopago', 'ref' => $tx['external_reference'] ?? null, 'id' => $playerId, 'tenant' => $game['tenant_id']]);
                }
            }
        } catch (\Throwable $e) {
            error_log('[ApPlanner Arena] Falha ao criar Pix do jogador: ' . $e->getMessage());
        }

        header('Location: /jogo/' . rawurlencode($token) . '?joined=1&participante=' . rawurlencode($private));
        exit;
    }

    public function waitlist(string $slug): void
    {
        CSRF::enforce();
        $ip = (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown');
        if (!RateLimiter::hit('arena-waitlist|' . $ip, 10, 3600)) HttpException::abort(429, 'Muitas tentativas. Aguarde alguns minutos.');
        $pdo = Database::connection();
        $tenant = $this->tenant($pdo, $slug);
        if (!$tenant) HttpException::abort(404, 'Arena não encontrada.');

        $name = trim((string)($_POST['name'] ?? ''));
        $phone = preg_replace('/\D/', '', (string)($_POST['phone'] ?? ''));
        $email = mb_strtolower(trim((string)($_POST['email'] ?? '')));
        $date = (string)($_POST['preferred_date'] ?? '');
        $courtId = (int)($_POST['court_id'] ?? 0) ?: null;
        $modalityId = (int)($_POST['modality_id'] ?? 0) ?: null;
        $duration = max(15, min(1440, (int)($_POST['duration_minutes'] ?? 60)));
        $flex = max(0, min(720, (int)($_POST['flexibility_minutes'] ?? 0)));
        $start = trim((string)($_POST['preferred_start'] ?? '')) ?: null;
        $end = trim((string)($_POST['preferred_end'] ?? '')) ?: null;
        if (mb_strlen($name) < 2 || strlen($phone) < 10 || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $date) || ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL))) {
            HttpException::abort(422, 'Revise os dados da lista de espera.');
        }
        $arenaCfg = $pdo->prepare('SELECT allow_waitlist FROM sports_arena_settings WHERE tenant_id=:tenant');
        $arenaCfg->execute(['tenant' => $tenant['id']]);
        $allowWaitlist = $arenaCfg->fetchColumn();
        if ($allowWaitlist !== false && !(bool)$allowWaitlist) HttpException::abort(403, 'A lista de espera está desativada nesta Arena.');
        if ($courtId) {
            $q = $pdo->prepare('SELECT 1 FROM sports_courts WHERE id=:id AND tenant_id=:tenant AND active=1');
            $q->execute(['id' => $courtId, 'tenant' => $tenant['id']]);
            if (!$q->fetchColumn()) HttpException::abort(422, 'Quadra inválida.');
        }
        if ($modalityId) {
            $sql = $courtId
                ? 'SELECT 1 FROM sports_modalities m JOIN sports_court_modalities cm ON cm.modality_id=m.id WHERE m.id=:id AND m.tenant_id=:tenant AND m.active=1 AND cm.court_id=:court'
                : 'SELECT 1 FROM sports_modalities m WHERE m.id=:id AND m.tenant_id=:tenant AND m.active=1';
            $q = $pdo->prepare($sql);
            $params = ['id' => $modalityId, 'tenant' => $tenant['id']];
            if ($courtId) $params['court'] = $courtId;
            $q->execute($params);
            if (!$q->fetchColumn()) HttpException::abort(422, 'Modalidade inválida para esta Arena.');
        }
        $customer = $this->customer($pdo, (int)$tenant['id'], $name, $phone, $email);
        $pdo->prepare(
            "INSERT INTO sports_waitlist(public_token,tenant_id,customer_id,court_id,modality_id,customer_name,customer_phone,customer_email,preferred_date,preferred_start,preferred_end,flexibility_minutes,duration_minutes,status,notes,created_at,updated_at)
             VALUES(:token,:tenant,:customer,:court,:modality,:name,:phone,:email,:date,:start,:end,:flex,:duration,'waiting',:notes,NOW(),NOW())"
        )->execute([
            'token' => bin2hex(random_bytes(16)), 'tenant' => $tenant['id'], 'customer' => $customer, 'court' => $courtId,
            'modality' => $modalityId, 'name' => $name, 'phone' => $phone, 'email' => $email ?: null, 'date' => $date,
            'start' => $start, 'end' => $end, 'flex' => $flex, 'duration' => $duration,
            'notes' => trim((string)($_POST['notes'] ?? '')) ?: null,
        ]);
        $canonical = (string)($tenant['public_slug'] ?: $tenant['public_short_code']);
        header('Location: /arena/' . rawurlencode($canonical) . '?waitlist=ok#lista-espera');
        exit;
    }

    public function court(string $slug, string $court): void
    {
        $pdo = Database::connection();
        $tenant = $this->tenant($pdo, $slug);
        if (!$tenant) HttpException::abort(404, 'Arena não encontrada.');
        $q = $pdo->prepare('SELECT slug FROM sports_courts WHERE tenant_id=:tenant AND slug=:court AND active=1 LIMIT 1');
        $q->execute(['tenant' => $tenant['id'], 'court' => $court]);
        if (!$q->fetchColumn()) HttpException::abort(404, 'Quadra não encontrada.');
        $canonical = (string)($tenant['public_slug'] ?: $tenant['public_short_code']);
        header('Location: /arena/' . rawurlencode($canonical) . '?quadra=' . rawurlencode($court) . '#reservar');
        exit;
    }

    private function gameRow(\PDO $pdo, string $token): array
    {
        $q = $pdo->prepare(
            "SELECT g.*,t.name tenant_name,t.public_slug,t.public_short_code,c.name court_name,m.name modality_name
             FROM sports_games g JOIN tenants t ON t.id=g.tenant_id JOIN sports_courts c ON c.id=g.court_id
             LEFT JOIN sports_modalities m ON m.id=g.modality_id
             WHERE g.public_token=:token LIMIT 1"
        );
        $q->execute(['token' => $token]);
        $row = $q->fetch();
        if (!$row) HttpException::abort(404, 'Racha não encontrado.');
        return $row;
    }

    private function tenant(\PDO $pdo, string $slug): array|false
    {
        $q = $pdo->prepare(
            "SELECT t.* FROM tenants t JOIN subscriptions s ON s.id=(SELECT MAX(s2.id) FROM subscriptions s2 WHERE s2.tenant_id=t.id)
             JOIN modules m ON m.slug='sports_courts' AND m.active=1
             LEFT JOIN plan_modules pm ON pm.plan_id=s.plan_id AND pm.module_id=m.id
             LEFT JOIN tenant_modules tm ON tm.tenant_id=t.id AND tm.module_id=m.id
             WHERE (t.public_slug=:slug OR t.public_short_code=:code) AND t.status IN('trial','active') AND t.deleted_at IS NULL
               AND COALESCE(tm.enabled,pm.enabled,0)=1 LIMIT 1"
        );
        $q->execute(['slug' => $slug, 'code' => $slug]);
        return $q->fetch();
    }

    private function customer(\PDO $pdo, int $tenantId, string $name, string $phone, string $email): int
    {
        $q = $pdo->prepare('SELECT id FROM customers WHERE tenant_id=:tenant AND phone=:phone LIMIT 1');
        $q->execute(['tenant' => $tenantId, 'phone' => $phone]);
        $id = (int)$q->fetchColumn();
        if ($id) return $id;
        $pdo->prepare("INSERT INTO customers(tenant_id,name,phone,email,status,created_at,updated_at) VALUES(:tenant,:name,:phone,:email,'active',NOW(),NOW())")
            ->execute(['tenant' => $tenantId, 'name' => $name, 'phone' => $phone, 'email' => $email ?: null]);
        return (int)$pdo->lastInsertId();
    }
}
