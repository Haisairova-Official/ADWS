# ADWS 1.35-S 正式版

内部版本：**S** · 构建日期：**2026-11-02** · 发布标签：`v1.35.2-S`

- 修复新版 Niri 下 Super／Ctrl 单键动作在按下时提前触发的问题，改为单独按下再松开才执行，避免干扰组合快捷键。
- 键位方案优先使用显式松开绑定，保留旧版修饰键轻按语法兼容，并增加新旧语法选择回归。
- 已有 ADWS 键位配置的用户升级后，请在输入与快捷键设置中重新应用一次当前键位方案。

Fix standalone Super/Ctrl actions firing on key press in newer Niri versions. Prefer explicit release bindings while retaining legacy modifier-tap compatibility. Added regression coverage for both configuration styles.

After upgrading, reapply your current keyboard profile in Input & Shortcuts settings to regenerate existing bindings.

界面显示 1.35-S；更新兼容标识为 1.35.2-S，供旧版本更新器正确识别此次更新。
Arch x86_64 提供预构建安装包；其他系统使用源码在目标系统构建。
