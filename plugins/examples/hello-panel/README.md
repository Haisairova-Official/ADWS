# Hello

ADWS panel 插件。运行 `adws mplg build plugins/examples/hello-panel` 打包，
然后把生成的 .mplg 丢到 `adws mplg dir` 显示的文件夹即可。

## 重复添加 / Multiple instances

默认允许重复添加，各实例独立保存布局及设置。在 `plugin.json` 顶层设置 `"isSingleOnly": true` 可限制为单例；`false` 或省略则可重复。该字段只接受 JSON 布尔值。宿主通过 `ADWS_PLUGIN_INSTANCE` 区分运行实例；详见 [Plugin API](../../../docs/mplg-spec.md)。

Plugins are repeatable by default. Use top-level `"isSingleOnly": true` for a single active instance, or omit it/use `false` for multiple instances. Each instance retains separate layout and settings. Use the `ADWS_PLUGIN_INSTANCE` environment variable to isolate writable instance state.
