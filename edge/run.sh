#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 0 ]]; then printf 'No arguments accepted; loopback binding is fixed.\n' >&2; exit 1; fi
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then printf 'Do not run this service as root.\n' >&2; exit 1; fi
if [[ ! -f "$ROOT/.env" || -L "$ROOT/.env" ]]; then printf 'Missing regular local .env. Run install.sh first.\n' >&2; exit 1; fi
# .env is trusted shell configuration; refuse shared/writable/foreign-owned files.
mode="$(stat -c '%a' "$ROOT/.env")"
owner="$(stat -c '%u' "$ROOT/.env")"
if [[ "$owner" != "$(id -u)" ]] || (( (8#$mode & 077) != 0 )); then
  printf '.env must be owned by you and private (manual fix: chmod 600 edge/.env).\n' >&2; exit 1
fi
set -a
source "$ROOT/.env"
set +a
export PYTHONDONTWRITEBYTECODE=1
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -m uvicorn service:app --host 127.0.0.1 --port 8765 --workers 1 --no-access-log --no-proxy-headers
