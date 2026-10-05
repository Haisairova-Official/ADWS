# ADWS 插件 / Plugins

`.mplg` 是包含 `plugin.json`、运行入口和可选翻译、README 的 ZIP 包。构建、安装及公开协议详见 [Plugin API v1.0](../docs/mplg-spec.md)。

## 是否允许重复添加

在 `plugin.json` **顶层**声明 `"isSingleOnly": true`，宿主将该插件视为单例，只允许一个活动组件。设置为 `false` 或不填写时允许重复添加。校验只接受 JSON 布尔值，不接受字符串 `"true"`、数字 `1` 或 `null`。

每份实例拥有独立标识、位置、顺序、宽度、动效和设置。移除一份不影响其他实例，也不删除包；重新添加优先恢复保留的配置。运行入口和控制命令通过 `ADWS_PLUGIN_INSTANCE` 获得实例标识，可用它隔离可写状态。

- [HelloWorld 示例](sample/README.md)
- [Hello 面板示例](examples/hello-panel/README.md)
- [NCMLyricsBar 歌词插件](netease-lyrics/README.md)

## English

A `.mplg` archive contains `plugin.json`, an entry point, and optional translations and README. See the [Plugin API v1.0](../docs/mplg-spec.md).

Set **top-level** `"isSingleOnly": true` for a single active component. Set it to `false`, or omit it, to allow multiple instances. Only JSON Booleans are accepted. Each instance retains separate placement, order, width, animations and settings. Entry and control commands receive the `ADWS_PLUGIN_INSTANCE` environment variable for isolating writable instance state. Removing one instance leaves the other instances and plugin package intact.

## 布局实时预览 / Live layout preview

宿主将运行中插件已校验的显示文本按实例保存到本次登录的临时目录。布局预览读取该快照，不会启动第二份插件，不缓存设置、命令或凭据。退出的运行器快照会被忽略，注销后随运行目录清理。插件不需要额外实现接口。

The host shares validated display text per instance in the login runtime directory. The layout preview reads this snapshot without starting another plugin or storing settings, commands or credentials. Snapshots from exited supervisors are ignored and the runtime directory clears at logout. No extra plugin interface is required.

## 插件运行监测 / Plugin watchdog

宿主为每份插件实例启动独立 watchdog，监测 Python 和 Rust 运行器的事件循环心跳。运行器异常退出或持续无响应时显示系统提示，并在“组件与插件”中将对应组件标黄、显示异常原因；其他实例继续运行。正常停止、移除或重载不报警，恢复正常运行后自动清除标记，同一实例一分钟内不重复弹出异常提示。不会自动无限重启。插件作者无需增加心跳代码，也不会因旧协议插件在暂停时没有歌词更新而误报。

An independent watchdog monitors each instance's Python/Rust supervisor event loop. Unexpected exits or sustained loss of responsiveness produce a desktop notification and a yellow warning with the reason in Components and Plugins. Normal stop/removal/reload does not warn; a healthy restart clears the warning. Alerts are limited to one per instance per minute. There is no unbounded restart loop, and plugins need no heartbeat implementation; legacy streams may remain quiet while paused.
