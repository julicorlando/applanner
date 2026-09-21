<?php
$root=dirname(__DIR__);
$checks=[];
$check=function(bool $ok,string $label)use(&$checks){$checks[]=[$ok,$label];echo ($ok?'[OK] ':'[FALHA] ').$label.PHP_EOL;};

$auth=(string)@file_get_contents($root.'/app/Core/Auth.php');
$controller=(string)@file_get_contents($root.'/app/Controllers/AuthController.php');
$service=(string)@file_get_contents($root.'/app/Core/TrustedDevice.php');
$challenge=(string)@file_get_contents($root.'/app/Views/auth/two-factor-challenge.php');
$security=(string)@file_get_contents($root.'/app/Views/auth/security.php');
$index=(string)@file_get_contents($root.'/index.php');
$migration=(string)@file_get_contents($root.'/database/migrations/042_two_factor_trusted_devices.sql');

$check(str_contains($auth,'TrustedDevice::isTrusted'),'Login consulta dispositivo confiável antes de exigir 2FA');
$check(str_contains($service,"private const DEFAULT_DAYS = 30"),'Prazo padrão de confiança é 30 dias');
$check(str_contains($service,"httponly'=>true") && str_contains($service,"samesite'=>'Lax'"),'Cookie confiável é HttpOnly e SameSite=Lax');
$check(str_contains($service,"hash('sha256',\$validator)"),'Token do dispositivo é persistido somente como hash');
$check(str_contains($service,'session_version'),'Dispositivo confiável é vinculado à versão de sessão');
$check(str_contains($controller,"remember_device") && str_contains($controller,'TrustedDevice::trust'),'Challenge pode registrar o dispositivo após 2FA válido');
$check(str_contains($controller,'TrustedDevice::revokeAllForUser'),'Alterações sensíveis revogam dispositivos confiáveis');
$check(str_contains($challenge,'Confiar neste dispositivo por 30 dias'),'Tela informa a confiança por 30 dias');
$check(str_contains($security,'Dispositivos confiáveis'),'Tela Segurança lista dispositivos confiáveis');
$check(str_contains($index,"/security/2fa/trusted-devices/revoke"),'Rota para revogar um dispositivo registrada');
$check(str_contains($index,"/security/2fa/trusted-devices/revoke-all"),'Rota para revogar todos registrada');
$check(str_contains($migration,'two_factor_trusted_devices'),'Migration 042 presente');
$check(!preg_match('/\b(DROP\s+TABLE|TRUNCATE|DROP\s+DATABASE)\b/i',$migration),'Migration não possui operação destrutiva');

$failed=array_filter($checks,fn($c)=>!$c[0]);
if($failed){fwrite(STDERR,"two factor trusted device static: FALHOU\n");exit(1);} 
echo 'two factor trusted device static: OK ('.count($checks).' verificações)'.PHP_EOL;
