# 安装器默认快捷键

默认键位参考 2026-11-06 本机 **实际生效** 的 Niri 配置：`binds.kdl`、主配置内的 `recent-windows`，以及主配置当时引用的 `.adws-keyboard-539e1df09da782bb9849.kdl`。只参考操作习惯；不复制个人脚本、应用路径、开机任务、显示器参数或旧桌面套件。

这套默认只用于目标机器尚无 Niri 配置时。集成、升级、重复安装及迁移到已有配置的机器，均保留原来的快捷键。生成器为 `tools/adws_install_niri.py`。

## 应用与常用操作

`Mod` 在普通 Niri 会话中是 Super（Windows 键）；嵌套运行时由 Niri 映射，不能把它与显式 `Super` 无条件合并。

| 快捷键 | 操作 |
| --- | --- |
| Mod+T、Mod+Return | 所选默认终端 |
| Mod+E | 所选默认文件管理器 |
| Mod+B | 所选默认浏览器 |
| Mod+Z | ADWS 开始菜单 |
| Mod+Alt+Comma | ADWS 设置；新增入口，不占用原来的列合并键 |
| Mod+Alt+L | 所选锁屏程序 |
| Mod+Alt+V | ADWS 剪贴板 |
| Mod+Alt+W | ADWS 壁纸设置 |
| Mod+Q、Mod+鼠标中键 | 关闭当前窗口 |
| Mod+O、Mod+G、Mod+Alt+G | Niri 总览 |
| 单独按下并松开 Super | 总览；仅在目标 Niri 支持松手动作时添加 |
| Mod+Shift+Slash | Niri 快捷键提示 |
| Mod+Shift+E | Niri 退出确认 |
| Mod+Escape | 切换快捷键抑制；作为远程桌面等应用的退出通道 |

终端的两个入口使用所选程序的真实命令，不给非 Kitty 终端强塞 `--single-instance`。本机当前有效的裸 Ctrl 动作为空，因此默认不绑定裸 Ctrl；早期未启用的片段里存在 Ctrl 开始菜单绑定，不作为此次依据。所选文本编辑器继续用于默认应用和文件关联，不占用本机用于截图翻译的 Mod+Shift+T。

默认应用候选排除 `NoDisplay` 的辅助入口，以及明确的后台服务模式，例如 `foot --server`、`foot -s` 和 `--daemon`；显式选择也遵守同一检查。正常 Foot、Kitty、Alacritty 启动入口保持可选。隐藏的文件关联处理器仍保留在迁移清单中，不因未出现在默认应用菜单而丢失。

## 窗口、列与多显示器

| 快捷键 | 操作 |
| --- | --- |
| Mod+方向键、Mod+H/J/K/L | 左右切换列，上下切换窗口 |
| Mod+A/D | 将窗口移入或移出相邻列 |
| Mod+W/S | 上下切换窗口 |
| Mod+Ctrl+方向键、H/J/K/L 或 W/A/S/D | 左右移动列，上下移动窗口 |
| Mod+Shift+方向键或 H/J/K/L | 跨显示器切换焦点 |
| Mod+Ctrl+Shift+方向键、H/J/K/L 或 W/A/S/D | 将整列移到对应显示器 |
| Mod+Alt+Shift+方向键、H/J/K/L 或 W/A/S/D | 将整个工作区移到对应显示器 |
| Mod+PageUp/PageDown、Mod+I/U | 上下切换工作区 |
| Mod+Ctrl+PageUp/PageDown、Mod+Ctrl+I/U | 将列移到上下工作区 |
| Mod+1…9 / Mod+Ctrl+1…9 | 切换工作区 / 移动列到工作区 |
| Mod+Home/End / Mod+Ctrl+Home/End | 聚焦首末列 / 移动列到首末 |
| Mod+左右方括号 | 将窗口移入或移出相邻列 |
| Mod+Comma、Mod+Shift+A | 将窗口合并到当前列 |
| Mod+Period、Mod+Shift+D | 将窗口移出当前列 |
| Mod+X、Mod+Shift+X | 切换列内标签页模式 |
| Mod+F / Mod+Alt+F | 最大化列 / 全屏 |
| Mod+V | 切换浮动状态 |
| Mod+Shift+V、Mod+N、Mod+Alt+N、Alt+grave | 切换平铺与浮动窗口焦点 |
| Mod+R / Mod+Shift+R / Mod+Ctrl+R | 切换预设列宽 / 窗口高度 / 重置高度 |
| Mod+C / Mod+Ctrl+C | 居中当前列 / 所有可见列 |
| Mod+Ctrl+F | 扩展列到剩余空间 |
| Mod+减号/等号 | 列宽减少/增加 5% |
| Mod+Shift+减号/等号 | 窗口高度减少/增加 5% |
| Mod+鼠标侧键 | 上下切换窗口 |

Mod+滚轮左右切换列焦点，加入 Ctrl 移动列；加入 Shift 改为上下工作区，Ctrl+Shift 移动列到上下工作区。工作区滚轮动作保留 150 ms 冷却时间。

窗口切换使用目标 Niri 自带的 `recent-windows`，不依赖个人 Fuzzel/Python 切换脚本：Mod+Tab 和 Mod+Shift+Tab 在当前工作区正反向选择窗口，Mod+grave 和 Mod+Shift+grave 选择同应用窗口，Alt+Tab 和 Alt+Shift+Tab 在全部窗口中正反向选择。目标版本不支持时报告跳过，不把 Tab 键悄悄改成总览。

## 截图、音量与亮度

| 快捷键 | 操作 |
| --- | --- |
| Print、Mod+Alt+A | Niri 区域截图 |
| Ctrl+Print、Mod+Ctrl+Alt+A | 当前窗口截图 |
| Shift+Print、Mod+Ctrl+Alt+Shift+A | 当前屏幕截图 |
| 音量加/减媒体键 | ADWS 音量增减 5 |
| 扬声器静音媒体键 | 切换默认输出静音 |
| 麦克风静音媒体键 | 切换默认输入静音 |
| 亮度加/减媒体键 | ADWS 亮度增减 5 |

锁屏、剪贴板、音频、亮度和壁纸操作只在用户选了对应功能，且选定命令与所需文件已安装后生成。音频、亮度媒体键允许在锁屏时操作，切换静音和锁屏等操作不随按键长按重复触发。亮度继续使用 ADWS 已有的合并提交和 DDC 限流后端；安装和快捷键校验不会读取显示器硬件。

截图直接使用 Niri 动作，不复制原机器上的截图音效脚本。首次壁纸提供 Niri 原生中性底色；已有壁纸进程仍显示在其上方，不为此多开后台服务。

## 能力差异与明确省略

每个键位、动作及参数都用目标 `niri validate` 实测，最终完整配置再次校验。版本字符串只记录来源，不代表功能一定存在。Mod+M 最小化、Mod+Shift+Z 放大镜、Mod+Alt+滚轮缩放与裸 Super 松手动作尤其不能假定官方版与分支版相同。不支持项进入安装报告；总览仍可用 Mod+O 或 Mod+G。

本机的快捷存档/读档、截图翻译、专属壁纸下载与随机轮换、第三方配色选择器、特定应用聚焦、个人 Waybar 布局切换、临时终端、强制结束进程及个人电源菜单依赖个人工具，不随默认配置照搬。这些项目列为 `personal-helper-not-part-of-portable-defaults`，不安装 Shorin/ML4W 实现。特别是 Alt+F4 原本调用个人强制结束脚本，这里不偷偷赋予强杀行为；可用 Mod+Q 正常关闭窗口。

生成时会拒绝重复键位，检查修饰键顺序与键名大小写；最终仍交由目标 Niri 校验，避免将不同运行模式下的 Mod/Super 错当成同一个键。测试覆盖了 Mod+L 不被锁屏覆盖、Mod+D 不被菜单覆盖，以及 Mod+Comma 不被设置入口覆盖。

## 已做的验证

2026-11-06 在本机分支版和隔离 Arch 根文件系统中的官方仓库 Niri `26.04 (8ed0da4)` 上运行 23 项生成器测试，包括真实配置生成、完整 `niri validate`、相对 include、重复安装保留用户修改和键位冲突回归。

官方版完整测试配置通过语法校验，生成 156 个可用键位；正确跳过最小化、三个放大镜键和裸 Super 松手。测试应用使用临时替身命令，不等于实际桌面操作已经验收。真实截图、窗口切换、硬件按键和输入法组合仍需在目标桌面会话的功能验收中检查。

另在 UID 1000 的隔离 Arch 环境，以独立 Xvfb、Niri 和 D-Bus 验证了自动选择的 `foot.desktop`：实际出现 `app_id=foot` 的终端窗口。该测试没有连接宿主桌面，也不代表 systemd 用户服务或实机图形驱动已经通过验收。
