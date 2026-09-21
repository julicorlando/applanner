<?php
declare(strict_types=1);

$root = dirname(__DIR__);
$failures = [];
$appointment = file_get_contents($root . '/app/Controllers/AppointmentController.php');
$availability = file_get_contents($root . '/app/Services/AvailabilityService.php');
$tenant = file_get_contents($root . '/app/Core/TenantContext.php');
$csrf = file_get_contents($root . '/app/Core/CSRF.php');

$checks = [
    'Agendamento valida tenant do cliente' => str_contains($appointment, "FROM customers WHERE id=:c AND tenant_id=:t"),
    'Agendamento valida tenant do profissional' => str_contains($availability, "FROM professionals WHERE id=:p AND tenant_id=:t AND active=1") && str_contains($appointment, 'professionalOffers'),
    'Agendamento verifica sobreposição' => str_contains($availability, "starts_at<:e AND ends_at>:s") && str_contains($appointment, 'isAvailable'),
    'Agendamento usa lock de concorrência' => str_contains($appointment, 'GET_LOCK'),
];
foreach ($checks as $label => $ok) if (!$ok) $failures[] = $label;
if (!str_contains($tenant, 'tenantId <= 0')) $failures[] = 'TenantContext bloqueia tenant ausente';
if (!str_contains($csrf, 'hash_equals')) $failures[] = 'CSRF usa comparação constante';

if ($failures) {
    fwrite(STDERR, "FALHOU:\n- " . implode("\n- ", $failures) . "\n");
    exit(1);
}
echo "OK: isolamento, CSRF, disponibilidade e concorrência presentes.\n";
