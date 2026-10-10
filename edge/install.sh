#!/usr/bin/env bash
# Explicit local dependency setup only; no SSH, apt, sudo, units or firewall edits.
set -euo pipefail
umask 077
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then printf 'Run as your normal board user, not root.\n' >&2; exit 1; fi
command -v python3 >/dev/null || { printf 'Install Python manually: sudo apt install python3 python3-venv\n'; exit 1; }
python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python >=3.10 required"'
if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv" || { printf 'If venv is missing, manually run: sudo apt install python3-venv\n'; exit 1; }
fi
"$ROOT/.venv/bin/python" -m pip install --only-binary=:all: -r "$ROOT/requirements.txt"
"$ROOT/.venv/bin/python" - "$ROOT/.env" <<'PY'
import os
import secrets
import sys
path = sys.argv[1]
if os.path.lexists(path):
    print('Existing .env preserved. Ensure EDGE_TOKEN is set and file permissions are private.')
else:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write('EDGE_TOKEN=' + secrets.token_urlsafe(48) + '\n')
        stream.write('EDGE_CAMERA=/dev/video0\nEDGE_WIDTH=640\nEDGE_HEIGHT=480\nEDGE_FPS=10\n')
        stream.write('EDGE_FRESHNESS_MS=2000\nPOSE_ONNX=\nPOSE_KEYPOINT_PERCENT=50\n')
    print('Created private .env with a new token (not printed).')
PY
printf 'Ready. Read OPERATIONS.txt; then run bash "%s/run.sh". No service installed or started.\n' "$ROOT"
