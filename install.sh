#!/usr/bin/env bash
# Convenience entry point; all installation logic lives in scripts/adws-install.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
source "$ROOT/scripts/adws-i18n.sh"

if [ "$#" -eq 0 ]; then
    exec bash "$ROOT/scripts/adws-install.sh"
fi
case "${1:-}" in
    -h|--help|'-?')
        adws_message "用法: ./install.sh" "Usage: ./install.sh"
        adws_message "检查依赖并安装 ADWS 配置及命令入口，保留已有配置。" "Check dependencies and install ADWS configuration and command links, preserving existing settings."
        adws_message "未安装 Niri 时，可选择系统软件源或官方源码构建；先检测 SDDM、Plasma Login Manager、GDM 或 LightDM，保留现有桌面与登录管理器。" "If Niri is missing, choose a repository package or an official source build; detect SDDM, Plasma Login Manager, GDM or LightDM first and preserve your existing desktop and login manager."
        adws_message "缺少依赖或组件时会询问是否安装、构建；支持 apt、pacman、dnf，Ctrl+C 取消。" "Offers to install or build missing dependencies and components; supports apt, pacman and dnf. Ctrl+C cancels."
        ;;
    *)
        adws_message "未知参数: $1；使用 ./install.sh --help 查看帮助。" "Unknown argument: $1; use ./install.sh --help for help." >&2
        exit 2
        ;;
esac
