<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require dirname(__DIR__) . '/app/Core/bootstrap.php';

use App\Core\{Database, Encryption};

$apply = in_array('--apply-safe', $argv, true);
$pdo = Database::connection();
$rows = $pdo->query("SELECT id,tenant_id,type,payload_encrypted,status,attempts,failed_at,last_error,created_at FROM jobs WHERE status='failed' ORDER BY id")->fetchAll() ?: [];
$eligible = [];
$other = [];

function reservedExampleEmail(string $email): bool {
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) return false;
    $domain = mb_strtolower((string)substr(strrchr($email, '@'), 1));
    return $domain === 'example.com' || str_ends_with($domain, '.example.com')
        || $domain === 'example.com.br' || str_ends_with($domain, '.example.com.br');
}

foreach ($rows as $job) {
    $payload = [];
    try { $payload = Encryption::decrypt((string)$job['payload_encrypted']); } catch (Throwable) {}
    $destination = (string)($payload['destination'] ?? $payload['to'] ?? '');
    if ($job['type'] === 'campaign.send' && ($payload['channel'] ?? '') === 'email' && reservedExampleEmail($destination)) {
        $eligible[] = [$job, $payload];
    } else {
        $other[] = [
            'id'=>(int)$job['id'], 'type'=>$job['type'], 'tenant'=>$job['tenant_id'],
            'attempts'=>(int)$job['attempts'], 'last_error'=>$job['last_error'] ?: 'sem diagnóstico histórico'
        ];
    }
}

echo "Jobs falhos: " . count($rows) . "\n";
echo "Falhas antigas seguras para converter em SKIPPED: " . count($eligible) . "\n";
foreach ($eligible as [$job,$payload]) {
    echo "  - job={$job['id']} tenant=" . ($job['tenant_id'] ?? '-') . " destino fictício/reservado\n";
}
if ($other) {
    echo "Outros jobs falhos (NÃO serão alterados):\n";
    foreach ($other as $j) echo "  - job={$j['id']} type={$j['type']} attempts={$j['attempts']} error={$j['last_error']}\n";
}

if (!$apply) {
    echo "\nDRY RUN. Use --apply-safe para corrigir SOMENTE destinatários example.com/example.com.br.\n";
    exit($other ? 2 : 0);
}

foreach ($eligible as [$job,$payload]) {
    $pdo->beginTransaction();
    try {
        $t = $job['tenant_id'];
        if (!empty($payload['recipient_id']) && $t) {
            $pdo->prepare("UPDATE campaign_recipients SET status='skipped' WHERE id=:id AND tenant_id=:t")
                ->execute(['id'=>$payload['recipient_id'],'t'=>$t]);
        }
        if (!empty($payload['automation_log_id']) && $t) {
            $pdo->prepare("UPDATE platform_automation_log SET status='skipped' WHERE id=:id AND tenant_id=:t")
                ->execute(['id'=>$payload['automation_log_id'],'t'=>$t]);
        }
        if (!empty($payload['notification_id']) && $t) {
            $pdo->prepare("UPDATE notifications SET status='skipped',error_message='Destinatário fictício descartado pelo RC1.' WHERE id=:id AND tenant_id=:t")
                ->execute(['id'=>$payload['notification_id'],'t'=>$t]);
        }
        if (!empty($payload['reminder_log_id']) && $t) {
            $pdo->prepare("UPDATE appointment_reminder_log SET status='skipped',error_message='Destinatário fictício descartado pelo RC1.' WHERE id=:id AND tenant_id=:t")
                ->execute(['id'=>$payload['reminder_log_id'],'t'=>$t]);
        }
        $pdo->prepare("UPDATE jobs SET status='completed',payload_encrypted='',locked_at=NULL,last_error='RC1: destinatário fictício descartado com segurança.',updated_at=NOW() WHERE id=:id AND status='failed'")
            ->execute(['id'=>$job['id']]);
        $pdo->commit();
    } catch (Throwable $e) {
        if ($pdo->inTransaction()) $pdo->rollBack();
        fwrite(STDERR, "[ERRO] job={$job['id']}: {$e->getMessage()}\n");
        exit(1);
    }
}
echo "[OK] Falhas de destinatários fictícios resolvidas sem envio de mensagens.\n";
if ($other) {
    echo "[ATENÇÃO] Ainda existem " . count($other) . " job(s) falho(s) reais para investigação.\n";
    exit(2);
}
