# Locale selection shared by shell entry points, including Python bootstrap.
adws_message() {
    local display_locale="${LC_ALL:-${LC_MESSAGES:-${LANG:-C}}}"
    local language="${LANGUAGE:-}"
    case "$display_locale" in C|C.*|POSIX) display_locale=C ;; *) display_locale="${language%%:*}"; display_locale="${display_locale:-${LC_ALL:-${LC_MESSAGES:-${LANG:-C}}}}" ;; esac
    case "$display_locale" in zh*|ZH*) printf '%s\n' "$1" ;; *) printf '%s\n' "$2" ;; esac
}
