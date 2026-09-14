#ifndef MNWS_I18N_H
#define MNWS_I18N_H
#include <stdlib.h>
#include <string.h>
#include <strings.h>
static inline const char *mnws_text(const char *zh, const char *en) {
    const char *locale = getenv("LC_ALL");
    if (!locale || !*locale) locale = getenv("LC_MESSAGES");
    if (!locale || !*locale) locale = getenv("LANG");
    if (!locale || !*locale || !strcmp(locale, "C") || !strncmp(locale, "C.", 2) || !strcmp(locale, "POSIX")) return en;
    const char *language = getenv("LANGUAGE");
    if (language && *language) locale = language;
    return !strncasecmp(locale, "zh", 2) ? zh : en;
}
#endif
