# 任务栏固定应用 / Pinned applications

右键应用卡片 → **固定到任务栏**；再次右键可取消固定。

- 本屏当前桌面没有窗口时显示固定图标，点击启动应用。
- 本屏当前桌面有窗口时，固定图标进入活动区；全部关闭后回到原来的固定位置。
- 本屏其他桌面有窗口时，固定图标显示三点角标，点击聚焦最近操作的窗口。
- 其他物理屏幕上的窗口不计入固定应用的运行状态。
- 固定应用多窗口始终合并，Peek 首项是最近操作的窗口，其余按桌面索引、平铺列、平铺行排序。
- 固定区有图标时始终显示末端分隔线，即使活动区为空，颜色实时复用聚焦卡片背景色；竖置任务栏使用横向分隔线。
- 普通未固定应用仍遵循原来的窗口合并与屏幕/桌面过滤设置。

Right-click an application card to pin or unpin it. Pins return to their saved position when the app has no windows on the current workspace. A three-dot badge indicates windows on another workspace of the same monitor. Click to focus the most recently used window; Peek lists it first, then the remaining windows in workspace/tile order. Windows on other physical monitors are treated as not running here. Launching uses the application's registered new-window action when available, otherwise its standard desktop launcher.

配置：`$XDG_CONFIG_HOME/adws/taskbar-pins.json`（默认 `~/.config/adws/taskbar-pins.json`）。保存应用 ID、桌面启动器 ID、名称和固定顺序，不保存易变的窗口 ID。写入加锁并原子替换；读取遇到无效文件时保留上一套有效配置。取消固定已卸载的应用不要求其启动器仍然存在。

验证：隔离 GTK 测试覆盖横/竖任务栏、跨桌面和多屏过滤、最近窗口单击聚焦、Peek 排序、关闭后归位、取消固定、空闲图标提示与实时分隔线配色；Python 测试覆盖固定顺序、别名去重、删除启动器后取消固定和损坏配置保护。
