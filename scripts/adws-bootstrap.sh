#!/usr/bin/env bash
# Verified release entry; no downloaded shell is piped into an interpreter.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.11+ is required. Install it using your system package manager first.' >&2
    exit 1
fi
exec python3 "$ROOT/tools/adws_bootstrap.py" "$@"
