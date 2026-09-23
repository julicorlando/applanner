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

function Wait-Healthy([string]$Service) {
    Write-Host "Aguardando $Service ficar saudável..."
    $tries = 0
    do {
        Start-Sleep -Seconds 2
        $container = docker compose @compose ps -q $Service
        $status = if ($container) {
            docker inspect --format='{{.State.Health.Status}}' $container 2>$null
        } else { "" }
        $tries++
    } until ($status -eq "healthy" -or $tries -ge 60)
    if ($status -ne "healthy") { throw "$Service não ficou saudável." }
}

Write-Host "Subindo bancos isolados de homologação..."
docker compose @compose up -d legacy-db migration-db
Wait-Healthy "legacy-db"
Wait-Healthy "migration-db"

$legacyDb = if ($env:LEGACY_CLONE_DATABASE) { $env:LEGACY_CLONE_DATABASE } else { "appnannerbr_planner" }
$legacyUser = if ($env:LEGACY_CLONE_USER) { $env:LEGACY_CLONE_USER } else { "legacy" }
$legacyPass = if ($env:LEGACY_CLONE_PASSWORD) { $env:LEGACY_CLONE_PASSWORD } else { "legacy-local-2026" }
$legacyRoot = if ($env:LEGACY_CLONE_ROOT_PASSWORD) { $env:LEGACY_CLONE_ROOT_PASSWORD } else { "legacy-root-local-2026" }

$targetDb = if ($env:MIGRATION_POSTGRES_DB) { $env:MIGRATION_POSTGRES_DB } else { "applanner_migration" }
$targetUser = if ($env:MIGRATION_POSTGRES_USER) { $env:MIGRATION_POSTGRES_USER } else { "applanner_migration" }

if ($legacyDb -notmatch '^[A-Za-z0-9_]+$' -or $legacyUser -notmatch '^[A-Za-z0-9_]+$') {
    throw "Nome de banco/usuário do clone MariaDB inválido."
}
if ($targetDb -notmatch '^[A-Za-z0-9_]+$' -or $targetUser -notmatch '^[A-Za-z0-9_]+$') {
    throw "Nome de banco/usuário PostgreSQL de homologação inválido."
}

Write-Host "Recriando clone MariaDB $legacyDb..."
$resetSql = "DROP DATABASE IF EXISTS $legacyDb; CREATE DATABASE $legacyDb CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; GRANT ALL PRIVILEGES ON $legacyDb.* TO '$legacyUser'@'%'; FLUSH PRIVILEGES;"
docker compose @compose exec -T legacy-db mariadb "-uroot" "-p$legacyRoot" -e $resetSql

Write-Host "Restaurando dump PHP/MariaDB..."
Get-Content -Raw -Encoding UTF8 $SqlPath |
    docker compose @compose exec -T legacy-db mariadb --default-character-set=utf8mb4 "-uroot" "-p$legacyRoot" $legacyDb

Write-Host "Parando aplicação antes de recriar o PostgreSQL de homologação..."
docker compose @compose stop web worker beat 2>$null

Write-Host "Recriando PostgreSQL isolado $targetDb..."
$terminate = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$targetDb' AND pid <> pg_backend_pid();"
docker compose @compose exec -T migration-db psql -U $targetUser -d postgres -v ON_ERROR_STOP=1 -c $terminate
docker compose @compose exec -T migration-db dropdb -U $targetUser --if-exists $targetDb
docker compose @compose exec -T migration-db createdb -U $targetUser $targetDb

Write-Host "Subindo Django contra o PostgreSQL de homologação..."
docker compose @compose up -d --force-recreate web
$tries = 0
do {
    Start-Sleep -Seconds 2
    $container = docker compose @compose ps -q web
    $state = if ($container) { docker inspect --format='{{.State.Status}}' $container 2>$null } else { "" }
    $tries++
} until ($state -eq "running" -or $tries -ge 60)
if ($state -ne "running") {
    docker compose @compose logs web --tail=150
    throw "Django de homologação não iniciou."
}

if ($Apply -and -not $env:LEGACY_APP_KEY) {
    throw "Para a homologação completa, configure LEGACY_APP_KEY localmente com a chave do PHP antigo."
}

Write-Host "Importando núcleo no PostgreSQL isolado..."
$coreArgs = @("python","manage.py","import_legacy_core")
if (-not $env:LEGACY_APP_KEY) {
    $coreArgs += "--skip-2fa"
}
docker compose @compose exec web @coreArgs

Write-Host "Importando módulos especializados..."
$specialArgs = @("python","manage.py","import_legacy_specialized")
if (-not $env:LEGACY_APP_KEY) {
    Write-Warning "LEGACY_APP_KEY não configurada: a base de pré-homologação será criada sem segredos, gateways, contas bancárias e prontuários."
    $specialArgs += "--skip-sensitive"
}
docker compose @compose exec web @specialArgs

Write-Host "Reposicionando sequences do PostgreSQL..."
docker compose @compose exec web python manage.py reset_db_sequences

if ($env:LEGACY_APP_KEY) {
    Write-Host "Auditando tabelas, IDs e cobertura de colunas em modo estrito..."
    docker compose @compose exec web python manage.py audit_legacy_parity --strict
} else {
    Write-Host "Auditando a pré-homologação; divergências sensíveis são esperadas sem LEGACY_APP_KEY..."
    docker compose @compose exec web python manage.py audit_legacy_parity
}

if ($Apply) {
    Write-Host "Aplicando RBAC adicional do Django após validar os dados legados..."
    docker compose @compose exec web python manage.py seed_rbac

    Write-Host "Subindo workers contra o banco homologado..."
    docker compose @compose up -d --force-recreate worker beat

    Write-Host ""
    Write-Host "Migração completa aplicada e auditada no banco isolado."
    Write-Host "Abra http://127.0.0.1:8000/ para homologar."
    Write-Host "Seu PostgreSQL local original não foi apagado."
} else {
    Write-Host ""
    Write-Host "Pré-homologação criada no PostgreSQL isolado."
    Write-Host "Abra http://127.0.0.1:8000/ para conferir os dados migrados."
    if (-not $env:LEGACY_APP_KEY) {
        Write-Host "Para validar também os dados criptografados, configure LEGACY_APP_KEY e rode novamente com -Apply."
    } else {
        Write-Host "A auditoria estrita foi executada. Use -Apply para habilitar o RBAC adicional e os workers da homologação."
    }
}

