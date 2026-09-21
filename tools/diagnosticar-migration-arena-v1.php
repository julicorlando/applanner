<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
$root = dirname(__DIR__);
require_once $root . '/app/Core/Database.php';
try {
    $pdo = \App\Core\Database::connection();
    $db = (string)$pdo->query('SELECT DATABASE()')->fetchColumn();
    echo "Banco: {$db}\n";
    $tables = [
        'sports_price_rule_extensions','sports_reservation_finance','sports_memberships','sports_membership_conflicts',
        'sports_games','sports_game_players','sports_waitlist','sports_classes','sports_class_students','sports_class_attendance',
        'sports_tournaments','sports_tournament_teams','sports_tournament_team_players','sports_tournament_matches',
        'sports_commands','sports_command_items','sports_command_stock_movements','sports_customer_metrics','sports_automation_logs',
        'tenant_payment_connections','tenant_payment_transactions','tenant_payment_webhook_events','sports_arena_settings','sports_membership_reservations'
    ];
    foreach ($tables as $table) {
        $q=$pdo->prepare('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=?');
        $q->execute([$table]);
        echo ((int)$q->fetchColumn() > 0 ? '[EXISTE] ' : '[FALTA]  ') . $table . "\n";
    }
    echo "\nConstraints fk_scm_* existentes:\n";
    $q=$pdo->query("SELECT CONSTRAINT_NAME,TABLE_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=DATABASE() AND CONSTRAINT_NAME LIKE 'fk_scm_%' ORDER BY CONSTRAINT_NAME");
    foreach ($q->fetchAll(PDO::FETCH_ASSOC) as $row) echo '- '.$row['CONSTRAINT_NAME'].' -> '.$row['TABLE_NAME']."\n";
    $q=$pdo->prepare('SELECT COUNT(*) FROM migrations WHERE migration=?');
    $q->execute(['037_applanner_arena_v1.sql']);
    echo "\nMigration 037 registrada: " . ((int)$q->fetchColumn() > 0 ? 'SIM' : 'NÃO') . "\n";
    echo "Diagnóstico concluído sem alterar dados.\n";
} catch (Throwable $e) {
    fwrite(STDERR, '[ERRO] '.$e->getMessage()."\n"); exit(1);
}
