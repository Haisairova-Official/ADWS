# Niri Desktop Layer

一个独立的桌面图标层 MVP：用 Python、GTK3 和 `gtk-layer-shell` 显示桌面目录，支持全桌面排列、框选多选、成组拖动，以及进入 Niri 概览时模糊图标。没有 Web 引擎，不接管壁纸、Waybar、窗口布局或文件管理器，也不会自动修改 Niri 配置、添加自启动或安装系统软件。

**图标位于普通窗口下方。运行后请切到空工作区查看；被窗口覆盖时看不到图标是预期行为。** 程序不提供收起 Niri 窗口的“显示桌面”快捷键。

## 开始使用

在当前 Niri 会话的终端中进入本项目目录：

```sh
./desktop-layer --check
./start-desktop-layer
```

`start-desktop-layer` 启动独立的临时 systemd 用户服务，关闭终端或 Codex 不会结束它。它不设置登录自启动，布局和视图偏好保存在项目内的 `state/layout.json`。直接运行 `./desktop-layer` 则以前台模式启动，并默认使用 XDG 状态目录。

首次运行使用 XDG 桌面目录；未配置桌面目录或配置为整个 HOME 时，使用 `~/Desktop`。缺失的目录不会被自动创建。默认监听桌面目录变化，使用 GIO 文件监视和事件合并，空闲时不周期扫描。

依赖为 Python 3.11+、PyGObject、PyCairo、GTK3、GtkLayerShell 和 Pillow。在本机 Arch 环境中，对应的 `python`、`python-gobject`、`python-cairo`、`gtk3`、`gtk-layer-shell`、`python-pillow`、`thunar` 已安装；项目本身没有安装步骤，启动脚本不会修改自身或系统配置。

常用控制命令可在另一个终端运行：

```sh
./desktop-layer --toggle   # 隐藏／恢复图标层
./desktop-layer --refresh  # 立即重新读取桌面目录
./desktop-layer --stop     # 退出图标层
```

这些命令在程序未运行时只显示提示，不会启动图标层。同一图形会话只有一个正式实例；修改启动参数后，先停止再重新运行。

想先在普通窗口中查看，可运行：

```sh
./desktop-layer --preview --state ./state/preview.json
```

预览与正式图标层是不同实例。用 `./desktop-layer --preview --stop` 关闭预览。

## 顶部 Waybar 联动

图标层读取并监听现有 `~/.local/state/taskbar-hidden` 状态文件。顶部 Waybar 的任务栏开关隐藏底部任务栏时，图标层同时隐藏；再次打开时同时显示。图标层启动时也读取当前状态，不会把已隐藏的任务栏状态反向切换。无需修改 Waybar 开关脚本。

图标和底部任务栏的开关采用约 220ms 淡入淡出；快速再次切换时从当前透明度反向过渡。隐藏时停止接收点击，动画结束后图标层取消映射，空闲不运行动画计时器。底栏通过 `modes.invisible` 保持绘制，使用 CSS 透明度过渡，立即释放输入；淡出期间继续保留占位，约 240ms 后由 `cffi/desktop-space` 释放空间。显示时 Waybar 先恢复占位，再淡入，避免窗口覆盖正在消失的底栏。模块仅在样式变化时响应，没有后台轮询，反向切换和卸载会取消延迟动作。配置修改前的备份在 `backups/*.before-fade`。

设置 `visibility_marker = ""` 可以关闭文件监听。桌面图标层与底部任务栏现在各自使用独立标记：桌面层用 `desktop-hidden`，任务栏用 `taskbar-hidden`。

## 选择、打开与排列

- 默认双击打开文件、文件夹和应用快捷方式；单击选中。
- 在桌面空白处拖出矩形框，多选与框相交的图标；按住 Ctrl 或 Shift 框选时保留已有选择。
- Ctrl + 单击切换单个图标的选中状态；Shift + 单击按当前页图标的视觉位置连续选择。
- 拖动选中组内的图标，整组保持相对位置移动；碰到桌面边界时整体约束，目标位置已有图标时将其移到腾出的空位。拖到普通文件夹图标或“主目录”等文件夹快捷方式上会把文件移入该文件夹，拖到回收站快捷方式上则移入回收站；否则只保存显示布局，不移动或重命名文件。
- 右击空白桌面、图标或点击工具条，打开菜单。空白处菜单提供新建文件夹、文本文档和 Markdown 文档；查看支持大／中／小图标；排序支持名称、类型、大小和修改日期，包含递增／递减和文件夹优先。排序会清除手动位置并真正重排图标。
- 图标菜单还提供打开、在文件管理器中显示、复制文件路径、删除（移到回收站）和属性。Delete 键删除选中项（移到回收站），Shift+Delete 在确认后永久删除。排序、尺寸和隐藏文件偏好会保存。
- 右键菜单中的“桌面配置…”可即时调整字体、字号与图标大小，偏好随布局一起保存。
- 项目超过一页时，在桌面图标层上滚动鼠标翻页。
- 悬停查看完整名称、路径和错误信息。

点击桌面后，可用 Ctrl + A 全选当前页、Esc 清除选择、Enter 打开选中项目。选择不会跨页保留，尚无方向键导航。

默认画布覆盖可用桌面，包括透明空白处都会接收鼠标，以支持框选。图标层仍在普通窗口下方，`exclusive_zone=0` 不占用平铺空间，并避开面板保留的区域。键盘模式为 `on-demand`：启动时不主动抢焦点，点击桌面后才允许获取焦点。

## Niri 概览效果

进入 Niri 概览时，仅对本程序的图标层内容（含工具条）做高斯模糊；退出概览后恢复清晰。壁纸和普通窗口不由本程序处理。

状态通过 `NIRI_SOCKET` 的 EventStream 直接监听，不运行后台 `niri` 命令，也不轮询概览状态。模糊结果缓存在内存中，内容或状态变化时重新生成，没有持续动画。概览期间图标层的鼠标输入区域清空，将交互交还给 Niri；键盘模式保持 on-demand，避免动态切换模式导致 Niri 意外退出总览。

本机用户选择让单按 Super 使用普通总览（`toggle-overview`），与 Super+O 一致。原自定义网格总览不发布该状态事件；本项目没有替换或编译 Niri。快捷键变更补丁与原始备份分别见 `super-overview-binding.patch` 和 `backups/binds.before-desktop-layer.kdl`。

默认 `overview_blur = 5`，设为 `0` 可关闭模糊效果。没有 Niri IPC 时仍可使用桌面图标；连接中断会恢复清晰，并进行最多六次指数退避重连。普通窗口预览不监听 Niri 概览。

## 配置

无需配置即可运行。完整默认值见 [config.example.toml](config.example.toml)。可在项目内复制并指定配置文件：

```sh
cp config.example.toml config.toml
./desktop-layer --config ./config.toml --state ./state/layout.json
```

也可以自行将配置放到 `~/.config/niri-desktop-layer/config.toml`。设置了 `XDG_CONFIG_HOME` 时使用其下同名路径。配置变更需要重启。

| 配置项 | 默认值 | 作用 |
| --- | --- | --- |
| `directory` | `""` | 空值使用 XDG 桌面目录；支持 `~` |
| `monitor` | `"primary"` | 主屏、`"all"`、接口名如 `"DP-1"`，或从 0 开始的序号字符串 |
| `icon_size` | `48` | 图标尺寸，24～96 |
| `cell_width` | `112` | 网格宽度，80～240 |
| `cell_height` | `104` | 网格高度，80～240 |
| `columns` | `0` | `0` 使用整个可用桌面；1～24 则限制为左侧指定列数的窄画布 |
| `overview_blur` | `5` | 概览时的高斯模糊半径，0～20；0 关闭效果 |
| `margin` | `18` | 画布边距，0～160 |
| `font_size` | `10` | 标签字号，8～20 |
| `font_family` | `"Noto Sans CJK SC"` | 图标名称与菜单字体（思源黑体的 Noto 版） |
| `show_hidden` | `false` | 显示以点开头的文件；仍尊重快捷方式的 Hidden/NoDisplay |
| `single_click` | `false` | 改为单击打开 |
| `sort_by` | `"name"` | name / type / size / modified |
| `sort_descending` | `false` | 递减排序 |
| `folders_first` | `true` | 文件夹始终优先 |
| `visibility_marker` | `"~/.local/state/desktop-hidden"` | 桌面图标层自身的显隐状态，空字符串关闭监听 |

图标和网格尺寸使用 GTK 逻辑像素；实际行列数由可用屏幕空间决定。网格必须容纳图标和两行文字，过小配置会报错退出。默认从左侧起按列排列，可拖动到整个桌面的网格位置，超出容量的项目分页显示。全桌面画布的缓冲区占用随分辨率和缩放变化；可设置 `columns = 4` 等非零值缩小画布。

Wayland 没有提供主屏时，`primary` 选择最靠左的显示器，位置相同时选择最靠上的显示器。`all` 在各屏镜像显示同一个桌面目录，并按显示器、页码分别保存位置。指定显示器未连接时，程序保持运行，等待连接。代码监听显示器增减；尚未进行实机拔插验证。

布局默认保存在 `~/.local/state/niri-desktop-layer/layout.json`，遵循 `XDG_STATE_HOME`，也可用 `--state` 指定项目内路径。拖动、重新排列或更改菜单偏好时写入，使用权限为 `0600` 的原子替换文件；无效、冲突或越界位置会自动重新分配。添加、删除文件导致分页边界变化时，部分图标可能重新排列。

## 快捷方式与文件打开

普通文件交给 GIO 默认关联程序打开。桌面文件夹、打开桌面目录和右键定位文件统一使用 Thunar；现有计算机、网络、回收站及家目录快捷方式也交给 Thunar。这里只改变本图标层的打开方式，不修改系统默认文件关联。可执行文本脚本交给默认文本编辑器；不会直接执行桌面上的脚本、ELF 或 AppImage。需要启动应用时，请使用对应的 `.desktop` 快捷方式。

`.desktop` 支持本地化名称、系统主题图标、`Type=Application` 和 `Type=Link`。Application 由 GIO 解析和启动，程序不自行拼接 shell 命令或展开 `Exec`。位于 XDG applications 目录中的启动器，包括指向其的符号链接，以及带可执行权限的启动器可直接打开；其他启动器先显示确认对话框，需点击“本次运行”。批量打开时依次确认，可以跳过单项或取消后续项目，后一个项目不会覆盖前一个确认。这次许可不会修改文件权限或持久化信任标记。

Link 仅接受 `file`、`http`、`https`、`trash`、`computer`、`network` 协议。损坏的快捷方式和失效符号链接保留为警告图标，可悬停查看原因。本机桌面已有的 `Steam++` 链接目标不存在，程序会提示该问题，不会修复、删除或修改它。

## 可选自启动

项目不会配置自启动。确认运行效果后，可自行在 Niri 配置中加入一行，并将路径改为项目实际位置：

```kdl
spawn-at-startup "/绝对路径/niri-desktop-layer/desktop-layer"
```

上面的路径是占位示例，不能直接使用。停止使用时运行 `--stop`，并删除自己添加的自启动行即可；Waybar 和壁纸无需更改。

## 命令行参数

| 参数 | 作用 |
| --- | --- |
| `--stop` / `--toggle` / `--refresh` | 控制已运行实例，三者互斥 |
| `--check` | 检查依赖并扫描桌面，输出 JSON，不创建窗口 |
| `--config PATH` | 指定 TOML 配置 |
| `--state PATH` | 指定布局状态 JSON |
| `--directory PATH` | 覆盖桌面目录 |
| `--monitor VALUE` | 覆盖显示器选择 |
| `--preview` | 用普通窗口预览；也可用于控制预览实例 |
| `--smoke-test SECONDS` | 正数秒数后自动退出 |
| `--diagnostics PATH` | 退出时写入运行诊断 JSON |
| `--snapshot PATH` | 退出时保存首个窗口的图标画布 PNG，不截取桌面 |
| `--help` | 显示帮助 |

## 验证与当前范围

无显示服务器的模型、配置、选择和概览事件测试：

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

在图形会话中可额外运行短暂自检：

```sh
./desktop-layer --smoke-test 5 --state ./state/test-layout.json \
  --diagnostics ./state/diagnostics.json --snapshot ./state/icons.png
```

自检应在正式实例停止后运行。它验证程序可以建立和退出图标层，并生成诊断；不等同于鼠标端到端操作测试。

隔离 Xvfb 图形测试覆盖菜单排序、偏好保存、框选、多选拖动、模糊恢复、属性和批量确认。概览监听已在本机真实 Niri IPC 上验证，可接收初始状态和开关变化；无显示测试覆盖消息拆包、状态变化、断线复位、重连上限和资源清理。全画布及模糊效果的实际资源占用取决于显示器和图标分布，不沿用窄画布版本的内存数据。

这是聚焦桌面取用的 MVP，尚无缩略图、文件删除、桌面内文件管理、跨应用文件拖放、方向键导航和管理 Niri 窗口的“显示桌面”功能。显示器拔插和真实鼠标操作的完整端到端流程仍需实机验证。

实现依据：[Niri Layer-Shell 组件说明](https://github.com/niri-wm/niri/wiki/Layer%E2%80%90Shell-Components)、[GtkLayerShell API](https://wmww.github.io/gtk-layer-shell/gtk-layer-shell.html)、[wlr-layer-shell 协议](https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-layer-shell-unstable-v1.xml)。

许可证：[MIT](LICENSE)。
