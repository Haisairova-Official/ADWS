#!/usr/bin/env bash
root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
exec python3 "$root/tools/adws_topbar_controls.py" toggle --refresh-indicator
