param(
    [Parameter(Mandatory=$true)]
    [string]$SqlPath,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$SqlPath = (Resolve-Path $SqlPath).Path
$compose = @(
    "-f","docker-compose.yml",
    "-f","docker-compose.local.yml",
    "-f","docker-compose.legacy.yml"
)

Write-Host "Subindo clone MariaDB legado..."
docker compose @compose up -d legacy-db

Write-Host "Aguardando MariaDB ficar saudável..."
$tries = 0
do {
    Start-Sleep -Seconds 2
    $container = docker compose @compose ps -q legacy-db
    $status = if ($container) { docker inspect --format='{{.State.Health.Status}}' $container 2>$null } else { "" }
    $tries++
} until ($status -eq "healthy" -or $tries -ge 60)

if ($status -ne "healthy") { throw "MariaDB legado não ficou saudável." }

$db = if ($env:LEGACY_CLONE_DATABASE) { $env:LEGACY_CLONE_DATABASE } else { "appnannerbr_planner" }
$user = if ($env:LEGACY_CLONE_USER) { $env:LEGACY_CLONE_USER } else { "legacy" }
$pass = if ($env:LEGACY_CLONE_PASSWORD) { $env:LEGACY_CLONE_PASSWORD } else { "legacy-local-2026" }

Write-Host "Restaurando dump em $db..."
Get-Content -Raw -Encoding UTF8 $SqlPath | docker compose @compose exec -T legacy-db mariadb "-u$user" "-p$pass" $db

Write-Host "Recriando web com conexão ao clone..."
docker compose @compose up -d --force-recreate web

Write-Host "Executando ETL em dry-run..."
docker compose @compose exec web python manage.py import_legacy_core --dry-run
docker compose @compose exec web python manage.py import_legacy_specialized --dry-run

if ($Apply) {
    Write-Host "Aplicando ETL..."
    docker compose @compose exec web python manage.py import_legacy_core
    docker compose @compose exec web python manage.py import_legacy_specialized
    Write-Host "Auditando paridade..."
    docker compose @compose exec web python manage.py audit_legacy_parity --strict
} else {
    Write-Host "Dry-run concluído. Rode novamente com -Apply para persistir a migração."
}
