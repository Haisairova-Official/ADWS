# Installation preflight; works before Python or other dependencies are present.
# A subshell keeps signal handlers local to this confirmation.
adws_confirm_install_session() (
    if [[ -z "${SSH_CONNECTION:-}${SSH_CLIENT:-}${SSH_TTY:-}" &&
          "${XDG_SESSION_TYPE:-}" != tty &&
          -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then
        return 0
    fi

    trap 'adws_message "已取消。" "Cancelled."; exit 130' INT
    adws_message "灵魂拷问：你是认真的吗？" "A soul-searching question: are you serious?"
    adws_message "当前处于 SSH 或非图形会话，仍要安装 ADWS？（y/N）" "You are in SSH or a non-graphical session. Install ADWS anyway? (y/N)"
    while true; do
        if ! IFS= read -r answer; then
            adws_message "已取消。" "Cancelled."
            return 1
        fi
        case "$answer" in
            y|Y|yes|YES|Yes) return 0 ;;
            ''|n|N|no|NO|No)
                adws_message "已取消。" "Cancelled."
                return 1
                ;;
            *) adws_message "请输入 y 或 n；直接回车取消。" "Enter y or n; press Enter to cancel." ;;
        esac
    done
)
