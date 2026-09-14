#!/usr/bin/env bash
# 读取底部任务栏开关状态，输出给 waybar
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
source "$ROOT/scripts/mnws-i18n.sh"
if [ -f "${XDG_STATE_HOME:-$HOME/.local/state}/taskbar-hidden" ]; then
    printf '{"text":"\uf108","class":"disabled","tooltip":"%s"}' "$(mnws_message '底部任务栏：已隐藏' 'Bottom taskbar: hidden')"
else
    printf '{"text":"\uf109","class":"enabled","tooltip":"%s"}' "$(mnws_message '底部任务栏：显示中' 'Bottom taskbar: visible')"
fi
