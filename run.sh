#!/usr/bin/env bash
# Wrapper: load variables from .env (if present) then run update_dns.py.
# Usage: ./run.sh [options passed to update_dns.py]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "${SCRIPT_DIR}/.env"
    set +a
fi

exec python3 "${SCRIPT_DIR}/update_dns.py" "$@"
