# HelloWorld — Plugin API v1.0 sample

From the ADWS root / 在 ADWS 根目录运行：

```sh
./adws mplg build plugins/sample
./adws mplg install plugins/org.adws.sample.HelloWorld_1.0.0.mplg
./adws mplg run org.adws.sample.HelloWorld
```

Enable it in Components and plugins / 在组件与插件设置中启用。
The host passes settings as JSON, handles rendering, and resolves `locale/` keys.
See [Plugin API](../../docs/mplg-spec.md).

## 重复添加 / Multiple instances

默认允许重复添加，各实例独立保存布局及设置。在 `plugin.json` 顶层设置 `"isSingleOnly": true` 可限制为单例；`false` 或省略则可重复。该字段只接受 JSON 布尔值。宿主通过 `ADWS_PLUGIN_INSTANCE` 区分运行实例；详见 [Plugin API](../../docs/mplg-spec.md)。

Plugins are repeatable by default. Use top-level `"isSingleOnly": true` for a single active instance, or omit it/use `false` for multiple instances. Each instance retains separate layout and settings. Use the `ADWS_PLUGIN_INSTANCE` environment variable to isolate writable instance state.
