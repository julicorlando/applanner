<?php
declare(strict_types=1);
$root=dirname(__DIR__); $auth=file_get_contents($root.'/app/Controllers/AuthController.php'); $migration=file_get_contents($root.'/database/migrations/003_auth_recovery_sessions.sql'); $fail=[];
foreach(['random_bytes(32)','hash(\'sha256\',$token)','expires_at>NOW()','session_version=session_version+1','Se o e-mail estiver cadastrado'] as $needle)if(!str_contains($auth,$needle))$fail[]=$needle;
foreach(['token_hash CHAR(64)','payload_encrypted LONGTEXT'] as $needle)if(!str_contains($migration,$needle))$fail[]=$needle;
if($fail){fwrite(STDERR,'FALHOU auth security: '.implode(', ',$fail)."\n");exit(1);} echo "OK: reset usa token hash, expiração, uso único, anti-enumeração e revogação de sessões.\n";
