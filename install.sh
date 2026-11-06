#!/usr/bin/env bash
# Convenience entry point; all installation logic lives in scripts/adws-install.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$ROOT/scripts/adws-i18n.sh"

case "${1:-}" in
    -h|--help|'-?')
        if command -v python3 >/dev/null && python3 -c 'import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
            exec python3 "$ROOT/tools/adws_install_workflow.py" --help
        fi
        adws_message "用法: ./install.sh [--mode fresh|integrate|migrate] [--plan] [--from-home PATH] [--resume] [--verify]" "Usage: ./install.sh [--mode fresh|integrate|migrate] [--plan] [--from-home PATH] [--resume] [--verify]"
        adws_message "先预览三种模式的依赖、配置和默认应用；持久保存进度，失败可续装。功能待验收不计为安装完成。" "Review dependencies, configuration and default apps first. Progress survives retries. Pending functional acceptance is not installation success."
        ;;
    *) exec bash "$ROOT/scripts/adws-install.sh" "$@" ;;
esac
