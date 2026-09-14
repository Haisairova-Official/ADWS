#!/usr/bin/env bash
# Convenience entry point; all installation logic lives in scripts/mnws-install.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$ROOT/scripts/mnws-i18n.sh"

if [ "$#" -eq 0 ]; then
    exec bash "$ROOT/scripts/mnws-install.sh"
fi
case "${1:-}" in
    -h|--help|'-?')
        mnws_message "用法: ./install.sh" "Usage: ./install.sh"
        mnws_message "检查依赖并安装 MNWS 配置及命令入口，保留已有配置。" "Check dependencies and install MNWS configuration and command links, preserving existing settings."
        mnws_message "缺少依赖或组件时会询问是否安装、构建；支持 apt、pacman、dnf，Ctrl+C 取消。" "Offers to install or build missing dependencies and components; supports apt, pacman and dnf. Ctrl+C cancels."
        ;;
    *)
        mnws_message "未知参数: $1；使用 ./install.sh --help 查看帮助。" "Unknown argument: $1; use ./install.sh --help for help." >&2
        exit 2
        ;;
esac
