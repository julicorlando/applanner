<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }

$root = dirname(__DIR__);
$file = $root . '/storage/private/rc1-acceptance.json';
$required = [
    'tenant_idor' => 'Empresa A não acessa dados da Empresa B (IDOR)',
    'billing_e2e' => 'Plano/assinatura/pagamento/webhook/ativação',
    'billing_module' => 'Módulo solicitado/aprovado/incorporado/liberado',
    'agenda' => 'Agenda criar/confirmar/remarcar/cancelar',
    'barber' => 'Barber check-in/comanda/estoque/comissão/financeiro',
    'arena_concurrency' => 'Arena bloqueia dupla reserva concorrente',
    'arena_payment' => 'Arena sinal/pagamento/conciliação',
    'auto' => 'Auto veículo/box/checklist/orçamento/comanda/entrega',
    'two_factor' => '2FA 30 dias + revogação',
    'lgpd' => 'Termos/aceite/consentimento/revogação conferidos',
];

$data = ['updated_at'=>null,'checks'=>[]];
if (is_file($file)) {
    $decoded = json_decode((string)file_get_contents($file), true);
    if (is_array($decoded)) $data = array_replace_recursive($data, $decoded);
}

$pass = null;
foreach ($argv as $arg) if (str_starts_with($arg, '--pass=')) $pass = substr($arg,7);
$reset = in_array('--reset', $argv, true);

if ($reset) {
    @unlink($file);
    echo "Aceites RC1 removidos.\n";
    exit;
}
if ($pass !== null) {
    if (!array_key_exists($pass, $required)) {
        fwrite(STDERR, "Chave inválida. Use uma destas:\n" . implode("\n", array_keys($required)) . "\n");
        exit(1);
    }
    if (!is_dir(dirname($file))) @mkdir(dirname($file), 0750, true);
    $data['checks'][$pass] = ['passed'=>true,'at'=>date(DATE_ATOM),'user'=>get_current_user()];
    $data['updated_at'] = date(DATE_ATOM);
    file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES), LOCK_EX);
    @chmod($file, 0640);
    echo "[OK] {$pass}: {$required[$pass]}\n";
}

echo "\nCHECKLIST RC1:\n";
foreach ($required as $key=>$label) {
    $done = !empty($data['checks'][$key]['passed']);
    echo ($done ? '[OK] ' : '[  ] ') . str_pad($key, 20) . " {$label}\n";
}
echo "\nApós testar manualmente, registre: php tools/rc1-acceptance.php --pass=CHAVE\n";
