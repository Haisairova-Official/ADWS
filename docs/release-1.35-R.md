# ADWS 1.35-R 正式版

内部版本：**R** · 构建日期：**2026-10-19**

- 修复托盘隐藏图标面板在 Wayland 下点击外部窗口或空白桌面后不收起的问题，关闭后恢复底栏焦点模式。
- 托盘状态刷新合并重复通知，避免持续更新打断状态读取；补充标准属性通知，及时更新图标、状态和提示。
- 临时缺失的托盘图片保留上一张有效图标，后续更新自动重试，减少微信等应用的图标消失。
- 补充真实 Niri 鼠标操作与资源清理回归，完善安装测试隔离；修正正式版小更新的版本识别。

Fix tray overflow dismissal, missed property notifications and temporary icon loading failures. Add real Niri input/cleanup coverage and preserve update compatibility.

发布标签使用 `v1.35.1-R`，使已安装的 1.35-Q 更新器能够识别并安装此次小更新；界面显示 1.35-R。作为新的 Latest 正式版取代 1.35-Q，保留旧版发布记录。

Arch x86_64 安装包包含预构建组件；Ubuntu、Mint 等系统应使用源码在目标系统构建。升级保留用户配置。
