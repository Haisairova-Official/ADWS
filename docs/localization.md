# Language files and randomized UI text

MNWS uses Chinese for a Chinese display locale and English for all other locales.
Display locale is selected from `LC_ALL`, then `LC_MESSAGES`, then `LANG`.
`LANGUAGE` supplies the preferred message language except in the C/POSIX locale.
The desktop, settings, CLI, installer and native menus use the same policy.
User filenames, custom labels, song titles and lyrics are not translated.

For translation contributors, see [Language.md](../Language.md).

Python UI strings use `tr(source_text)` and the English catalogue in `language/en.json`.
Named reusable messages are stored under `_messages` in both `language/zh.json` and
`language/en.json`. A message can be a string or a list of weighted variants:

```json
{
  "_messages": {
    "updates.none": [
      {"weight": 80, "text": "No updates found."},
      {"weight": 20, "text": "You're up to date!"}
    ]
  }
}
```

Use `message("updates.none")` from `mnws_i18n` (tools) or `desktop_layer.i18n`
(desktop). Each call makes one selection. Weights must be finite positive numbers;
they are relative and need not add up to 100. Each language may supply its own
wording and weights. UI code does not contain the 80/20 probabilities.

中文说明：将可复用的文案放入语言文件的 `_messages`。普通文案使用字符串；
概率彩蛋使用含 `weight` 和 `text` 的列表。调用 `message("键名")` 即可按当前
显示语言和权重抽取一条。每次抽取相互独立，并不保证十次中恰好出现八次和两次。

## Update checks / 检查更新

`mnws --update` and `mnws -u`, or **About → Check for updates**, query the
[GitHub latest stable Release API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).
The check only reports a version and a GitHub release link; it never installs code.

To choose the route, MNWS queries `https://api.country.is/` for the country of its
outbound IP. It does not store or print the IP. For `CN`, it first tries
`https://gh-proxy.com/`, whose [service documentation](https://gh-proxy.com/)
lists GitHub API support, then falls back to GitHub directly on error. If location
detection fails, it uses GitHub directly. `MNWS_GITHUB_PROXY` can override the HTTPS
proxy prefix; an empty value disables the proxy. No GitHub credentials are sent.

检查更新只会在用户点击按钮或执行命令时联网。通过出口 IP 国家代码判断中国大陆，
优先代理，失败后直连；定位失败则直连。没有可用网络或响应格式错误时显示失败，
不会触发“未检测到更新”的概率文案。没有新的正式 Release 时才抽取一次文案。

Only published stable Releases count. Commits pushed to a branch without a Release
will not trigger an update notification.
