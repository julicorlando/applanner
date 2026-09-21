#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAYLOAD="$ROOT/patches/applanner-pre-homologacao-limpa-v1/payload"
PHP_BIN="${PHP_BIN:-php}"
export APPLANNER_ROOT="$ROOT"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

export APPLANNER_PREHOMOLOG_STATE="/tmp/applanner-prehomolog-state-$$.json"
CODE_TMP="/tmp/applanner-prehomolog-code-$$"

on_err() {
  code=$?
  echo
  echo "[ERRO] Instalação interrompida (exit=$code)." >&2
  if [[ -f "$APPLANNER_PREHOMOLOG_STATE" ]]; then
    echo "[INFO] Estado/backup temporário:" >&2
    "$PHP_BIN" "$ROOT/tools/pre-homologation-backup-helper.php" state 2>/dev/null || true
  fi
  [[ -d "$CODE_TMP" ]] && echo "[INFO] Backup temporário de código: $CODE_TMP" >&2
  exit "$code"
}
trap on_err ERR

if [[ ! -d "$PAYLOAD" ]]; then
  echo "[ERRO] Payload não encontrado: $PAYLOAD" >&2
  exit 1
fi

echo "APPLANNER - INSTALADOR V1.1 (SEM PHP exec())"
echo "============================================="
echo "[INFO] ROOT=$ROOT"
echo "[INFO] PAYLOAD=$PAYLOAD"
echo "[INFO] PHP=$("$PHP_BIN" -r 'echo PHP_BINARY." ".PHP_VERSION;' 2>/dev/null || echo "$PHP_BIN")"
"$PHP_BIN" -d display_errors=1 -d display_startup_errors=1 -d error_reporting=E_ALL "$PAYLOAD/tools/preflight-pre-homologation-clean.php"
echo
"$PHP_BIN" -d display_errors=1 -d display_startup_errors=1 -d error_reporting=E_ALL "$PAYLOAD/tools/pre-homologation-clean.php"

if [[ "$DRY" -eq 1 ]]; then
  echo
  echo "DRY RUN: OK. Nenhuma alteração foi feita."
  exit 0
fi

# Helper must be available at root before use.

"$PHP_BIN" "$ROOT/tools/pre-homologation-backup-helper.php" prepare

echo "[2/10] Salvando temporariamente arquivos que serão alterados..."
mkdir -p "$CODE_TMP"
while IFS= read -r -d '' src; do
  rel="${src#"$PAYLOAD/"}"
  current="$ROOT/$rel"
  if [[ -f "$current" ]]; then
    mkdir -p "$CODE_TMP/$(dirname "$rel")"
    cp -p "$current" "$CODE_TMP/$rel"
  fi
done < <(find "$PAYLOAD" -type f -print0)
echo "[OK] Backup temporário de código: $CODE_TMP"

echo "[3/10] Instalando código de homologação sem demo..."
cp -a "$PAYLOAD"/. "$ROOT"/
while IFS= read -r -d '' f; do
  "$PHP_BIN" -l "$f" >/dev/null
done < <(find "$PAYLOAD" -type f -name '*.php' -print0)
echo "[OK] Payload copiado e PHP lint aprovado."

echo "[4/10] Removendo demo, históricos e backups antigos..."
"$PHP_BIN" "$ROOT/tools/pre-homologation-clean.php" --apply

"$PHP_BIN" "$ROOT/tools/pre-homologation-backup-helper.php" baseline

"$PHP_BIN" "$ROOT/tools/pre-homologation-backup-helper.php" finish

echo "[7/10] Validando ausência de demo e base limpa..."
"$PHP_BIN" "$ROOT/tests/no_demo_smoke.php"
"$PHP_BIN" "$ROOT/tests/rc1_regression_static.php"
echo "[OK] Smoke/regression aprovados."

echo "[8/10] Conferindo sequências AUTO_INCREMENT..."
"$PHP_BIN" "$ROOT/tools/id-sequence-status.php" | head -n 25 || true
echo "..."

echo "[9/10] Executando GO técnico externo..."
"$PHP_BIN" "$ROOT/tools/rc1-go-live.php" --external

echo "[10/10] Removendo backup temporário de código..."
rm -rf "$CODE_TMP"
trap - ERR

echo
echo "PRE-HOMOLOGAÇÃO LIMPA CONCLUÍDA."
echo "- RF Films preservada"
echo "- Master preservado"
echo "- 0 demos"
echo "- logs antigos limpos"
echo "- backups antigos removidos"
echo "- backup-base novo ID 1"
echo "- verification ID 1"
echo "- tabelas vazias: próximo ID 1"
echo "- tabelas com dados: próximo ID MAX(id)+1"
