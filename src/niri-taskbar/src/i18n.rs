pub fn text<'a>(zh: &'a str, en: &'a str) -> &'a str {
    let get = |key| std::env::var(key).ok().filter(|s| !s.is_empty());
    let locale = get("LC_ALL").or_else(|| get("LC_MESSAGES")).or_else(|| get("LANG")).unwrap_or_else(|| "C".into());
    let chinese = if locale == "C" || locale.starts_with("C.") || locale == "POSIX" {
        false
    } else {
        get("LANGUAGE").unwrap_or(locale).split(':').next().unwrap_or("").to_lowercase().starts_with("zh")
    };
    if chinese { zh } else { en }
}
