# 任务栏组件 / Taskbar components

布局页提供实时预览：添加、移除、移动和配置组件时即时刷新，方向、高度、图标、图片、时钟格式及配色跟随当前草稿。点击预览可直接选中对应组件，拖动可排序或跨区域移动。窗口图标、分组、聚焦状态、托盘和歌词读取当前运行内容；插件尚未启动时显示组件名称，预览不会额外启动插件进程。

任务栏布局使用「添加组件」菜单管理。前部、中间、后部均横向展示，可在卡片列表或预览中拖动排序、跨区移动；选中卡片后在右侧调整位置、顺序、占位宽度和设置。

| 组件 | 可重复添加 | 可移除 |
| --- | --- | --- |
| 开始按钮 | 是，每个实例独立设置图标、图片与启动器 | 是 |
| 时钟 | 是，每个实例独立设置时间与日期格式 | 是 |
| 工作区 | 否 | 是 |
| 窗口图标栏 | 否，始终保留一个 | 否，也不可停用 |
| 声音、亮度、系统托盘 | 否，每类最多一个 | 是 |
| `.mplg` 插件 | 未声明 `isSingleOnly: true` 时可重复，每份实例独立设置 | 是 |

移除插件只影响任务栏布局，不删除 `.mplg` 文件和插件设置。可从添加菜单恢复。开始按钮设置页有实例选择器；原有开始菜单主题、快捷键和动效继续使用全局设置。每个开始按钮的菜单位置由实际点击的按钮决定。

布局文件仍为 `~/.config/adws/taskbar-layout.json`。`apiVersion: 2` 的 `builtins` 是明确的实例列表：`id` 指定组件类型，`instance` 是稳定且唯一的实例标识，`options` 覆盖该实例的全局默认设置。可选组件缺席时不会被自动补回。旧版配置在读取时自动迁移，原有位置、顺序与插件设置保留；保存时写入新格式。

```json
{
  "apiVersion": 2,
  "builtins": [
    {"id": "start", "instance": "start", "slot": "left", "order": 0},
    {"id": "windows", "instance": "windows", "slot": "left", "order": 1},
    {"id": "start", "instance": "start-second", "slot": "right", "order": 0,
     "options": {"start_label": "Apps", "start_launcher_mode": "fuzzel", "start_launcher_command": "fuzzel"}}
  ],
  "plugins": [],
  "options": {"start_launcher_mode": "adws"}
}
```

The live preview follows unsaved placement, ordering, visibility, Start images and labels, clock formats, direction, thickness and colours. Click a preview component to select it. Window icons, grouping, focus, tray icons and plugin text come from read-only live snapshots. Unstarted plugins show their name. The preview does not start extra plugin processes. Drag components to reorder them or move them across regions.

Use **Add component** to build the layout. Components appear horizontally in Front, Center and Back; drag cards to reorder or move across regions.  selecting a card opens its placement, order, width and settings in the inspector.

Start buttons and clocks can be added repeatedly, each with independent preferences. Workspaces, sound, brightness and the tray are optional singletons. Plugins can repeat unless they declare `isSingleOnly: true`; each instance keeps independent settings. Window icons are required: exactly one remains enabled, including after importing or manually editing a layout. Removing a plugin preserves its package and preferences so it can be added again.

The Start settings page provides an instance selector. Menu themes, keyboard bindings and animations remain global; button appearance and launcher choice are per instance. Menus open at the button that was clicked.

Version 2 separates component type (`id`) from stable instance identity (`instance`). Per-instance `options` override global defaults. Optional components are no longer implicitly restored. Legacy layouts migrate on load while preserving placement, order and plugin settings, and save in the new format.

设计参考 / Design reference: [Clavis component loader and sidebars](https://github.com/StatIndet/quickshell). ADWS 的编辑器沿用自身 GTK 与配色框架，独立实现组件实例及侧栏编辑。

## 默认布局 / Default layout

| 区域 / Region | 组件 / Components |
| --- | --- |
| 前部 / Front | 开始按钮、窗口图标 / Start, window icons |
| 中间 / Center | 无 / Empty |
| 后部 / Back | 声音、亮度、系统托盘、时钟 / Sound, brightness, tray, clock |

默认布局用于新安装或手动恢复默认布局，已有布局保留。保存个人布局不会改写随源码附带的默认配置。
The defaults apply to new installations or an explicit reset; existing layouts are preserved. Saving a personal layout never overwrites the shipped default file.
