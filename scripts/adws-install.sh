#!/usr/bin/env bash
# 把 ADWS 配置安装到当前运行环境（幂等，可重复执行）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/adws-i18n.sh"
# Ask before dependency installation, backups, or stopping existing components.
# The transaction re-enters this script after the outer invocation confirmed.
if [ "${ADWS_INSTALL_TRANSACTION:-}" != "$ROOT" ]; then
    source "$ROOT/scripts/adws-install-session.sh"
    if [[ " $* " != *" --plan "* && " $* " != *" --verify "* ]]; then
        adws_confirm_install_session || exit "$?"
    fi
fi
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/waybar"
LOCAL_BIN="$HOME/.local/bin"

# Offer dependency repair before changing user configuration.
if ! command -v python3 >/dev/null 2>&1; then
    if [[ " $* " == *" --plan "* || " $* " == *" --verify "* ]]; then
        adws_message "需要 Python 3.11+ 才能生成计划；只读模式不会安装依赖。" "Python 3.11+ is needed to plan; read-only mode will not install it."
        exit 1
    fi
    adws_message "缺少 Python 3，是否现在安装？（Y/n/Ctrl+C）" "Python 3 is missing. Install it now? (Y/n/Ctrl+C)"
    read -r answer || { adws_message "已取消。" "Cancelled."; exit 1; }
    case "$answer" in
        ""|y|Y)
            if command -v apt-get >/dev/null; then packages=(apt-get install python3)
            elif command -v pacman >/dev/null; then packages=(pacman -S python)
            elif command -v dnf >/dev/null; then packages=(dnf install python3)
            else adws_message "请使用系统软件管理器安装 Python 3.11+ 后重试。" "Install Python 3.11+ using your system package manager, then retry."; exit 1; fi
            if [ "$EUID" -ne 0 ]; then packages=(sudo "${packages[@]}"); fi
            "${packages[@]}" || { adws_message "Python 安装失败，请检查软件源后重试。" "Python installation failed. Check your package repositories and retry."; exit 1; }
            ;;
        *) adws_message "已取消。" "Cancelled."; exit 1 ;;
    esac
fi
if ! python3 -c 'import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
    adws_message "需要 Python 3.11+；请先升级解释器。" "Python 3.11+ is required; upgrade the interpreter first."
    exit 1
fi
if [ "${ADWS_INSTALL_TRANSACTION:-}" != "$ROOT" ]; then
    exec python3 "$ROOT/tools/adws_install_workflow.py" "$@"
fi
# Source-installed Niri uses the standard local prefix; append without shadowing
# a custom compositor already selected by the user's PATH.
case ":$PATH:" in *:/usr/local/bin:*) ;; *) export PATH="$PATH:/usr/local/bin" ;; esac
if [ "${ADWS_INSTALL_CONFIG_ONLY:-}" != 1 ]; then
    python3 "$ROOT/tools/adws_setup.py"
fi
if [ "${ADWS_INSTALL_CONFIG_ONLY:-}" = 1 ]; then
    # Legacy directories were reviewed and imported at transaction start.
    # This stage initializes bundled packages only, never moves old user trees.
    python3 "$ROOT/tools/adws_migrate.py" --managed-init
else
    python3 "$ROOT/tools/adws_migrate.py"
fi
if [ "${ADWS_INSTALL_CONFIG_ONLY:-}" = 1 ]; then
    LAUNCHER=""
else
    python3 "$ROOT/tools/adws_windows.py"
    LAUNCHER="$(python3 "$ROOT/tools/adws_launcher.py" --select)"
fi
mkdir -p "$LOCAL_BIN" "$CONFIG_DIR"
for file in config-bottom.jsonc style-bottom.css modules.jsonc colors.css; do
    target="$CONFIG_DIR/$file"
    python3 "$ROOT/tools/adws_include.py" --detach-template "$target"
    if [ -e "$target" ] || [ -L "$target" ]; then
        adws_message "保留现有配置: $target" "Keeping existing configuration: $target"
    else
        cp "$ROOT/config/waybar/$file" "$target"
        python3 "$ROOT/tools/adws_uninstall.py" --record-config "$target"
        adws_message "已安装默认配置: $target" "Installed default configuration: $target"
    fi
done

python3 "$ROOT/tools/adws_topbar.py" --install-defaults

python3 "$ROOT/tools/adws_include.py" "$CONFIG_DIR/config-bottom.jsonc"
if [ "${ADWS_INSTALL_CONFIG_ONLY:-}" = 1 ]; then
    python3 "$ROOT/tools/adws_launcher.py" --apply-install-plan
else
    python3 "$ROOT/tools/adws_launcher.py" --apply "$CONFIG_DIR/modules.jsonc" "$LAUNCHER"
    python3 "$ROOT/tools/adws_launcher.py" --save-selection "$LAUNCHER"
fi
python3 "$ROOT/tools/adws_health.py" --init-desktop

python3 "$ROOT/tools/adws_commands.py"
python3 "$ROOT/tools/adws_uninstall.py" --record
# Restore saved components and their menus after a fresh/reinstalled base config.
if [ ! -L "$CONFIG_DIR/config-bottom.jsonc" ]; then
    "$ROOT/adws" layout apply
fi
"$ROOT/adws" -v
if [ "${ADWS_INSTALL_CONFIG_ONLY:-}" != 1 ]; then
    python3 "$ROOT/tools/adws_autostart.py"
    python3 "$ROOT/tools/adws_topbar.py" --offer-autostart
    python3 "$ROOT/tools/adws_niri_compat.py" offer
fi
adws_message "配置部署结束；请完成 Niri 会话中的功能验收。" "Configuration deployed; complete functional acceptance in the Niri session."
