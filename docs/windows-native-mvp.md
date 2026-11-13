# Windows 原生后端 MVP / Experimental Windows support

状态：工程原型，可编译；**尚未完成 Explorer-free VM 登录验收，不应设置为日常账户 Shell**。
开发分支：`Experimental-WinSupport`。基线：`9c951728f3714e61f4e0639584bbaec26faaee82`。

## 仓库核查与分阶段计划

2026-11-13 核实公开仓库为 `Haisairova-Official/ADWS`，默认分支 `main`；
连接账号 `Haisairova-Official`，GitHub 返回 admin/maintain/push/pull 权限。
原有 `src/adws-runtime` 是 Rust + libc 插件进程监督器，GTK/Niri 组件仍有 Linux 平台依赖。
`docs/mplg-spec.md` 定义的是 `.mplg` 面板显示协议，不是窗口管理后端接口。
本变更不改动 Linux 安装与发布路径。

| 阶段 | 可执行工作与完成条件 | 当前情况 |
| --- | --- | --- |
| A：协议与工程 | 独立分支；能力声明；纯布局与 Win32 分离；明确插件复用边界 | 已实现 |
| B：后端与 WM | EnumWindows、WinEvent、窗口过滤、分屏平铺、焦点与可替换策略进程；协议失败测试通过 | 已实现，真实窗口行为待 VM 验收 |
| C：Shell Host | 常驻恢复进程、独立工作进程、启动入口、文件管理器配置、故障停止和恢复 | 已实现，崩溃／挂起 UI 待 VM 验收 |
| D：隔离验收 | VM 快照；测试账户；Explorer-free 登录；混合 DPI、权限窗口、恢复矩阵 | 待执行；不得以编译代替验收 |
| E：产品化 | Desktop 三态、面板/托盘/通知、原有配置桥接、滚动 WM、可靠安装回滚 | 后续范围 |

## 架构与取舍

```text
ADWS Guardian（常驻恢复窗口；未来可作为登录 Shell 入口）
  └─ ADWS Host（WinForms 控制面板、配置、快捷键、Win32Backend）
       ├─ WM 模块（独立进程；stdin/stdout JSON lines）
       └─ 用户应用／独立文件管理器（停止 ADWS 后继续运行）
USER32 提供窗口操作；DWM 保持合成职责
```

Windows 工程位于 `src/adws-windows/`，采用 C#/.NET 8 + Win32 P/Invoke。
这是 Windows 专属的原生 API 后端，不是原有 Rust/GTK 桌面的完整移植；选择此方案是为了
使用现有 Windows SDK 环境快速交付可构建的原型，布局数据与协议仍可由 Rust/C++ 模块实现。
目前启动界面是诊断控制面板，不代表最终桌面外观。

- `Adws.Windows.Core`：数据模型、JSON framing、矩形验证、无平台布局算法、应用启动配置。
- `Adws.Windows.Host`：Win32Backend、独立恢复窗口、事件循环、能力调用、策略监督。
- `Adws.Windows.Wm`：可替换的示例等宽列平铺进程；不是 Niri 滚动平铺。
- `Adws.Windows.Tests`：无需桌面操作的布局、协议和子进程故障测试。

不实现合成器、不注入进程、不使用未公开虚拟桌面接口。现有 `.mplg` 格式及协议不变；
新 WM 仅复用 UTF-8 JSON 行、stdout 专用于协议、stderr 日志、1 MiB 上限和进程隔离约定。
没有宣称现有 Python 面板插件可直接加载，也未引入新的 `.mplg` renderer。
Desktop 的完整／仅右键／关闭三态保留为后续模块职责；文件管理器不属于 Desktop 模块。

## 构建与启动（Windows x64）

需要 .NET 8 或更新 SDK；运行产物需要 .NET 8 Desktop Runtime x64。
从仓库根目录执行：

```powershell
./src/adws-windows/build.ps1
```

产物位于 `src/adws-windows/artifacts/win-x64/`。构建不启动 Shell、不改系统设置。
将整个目录复制到 VM；不要只复制 EXE。按需把随附 `windows-config.example.json`
复制为同目录 `windows-config.json`，填写实际存在的独立文件管理器路径；示例路径不是自动安装器。
不配置文件管理器时 Files 按钮明确报错，不回退启动 Explorer。
所有启动命令用 executable + 参数数组，不经过 shell 字符串解释。配置和模块属于受信任的本地代码。

只读诊断（不移动／聚焦窗口、不注册快捷键、不启动用户应用）：

```powershell
./src/adws-windows/artifacts/win-x64/Adws.Windows.Host.exe --inspect --output snapshot.json
```

快照包含窗口标题与进程 ID，请勿无意公开。该清单只包含符合 MVP 管理条件的窗口。

仅在 VM 或专用测试账户运行：

```powershell
./Adws.Windows.Host.exe --test-session
```

`--test-session` 是明确的测试启动开关，不是自动识别 VM 的安全边界。
默认显示恢复窗口和控制面板，**自动平铺关闭**；点击 Tile 或勾选自动平铺后才移动窗口。
快捷键为 Ctrl+Alt+T（终端）、Ctrl+Alt+L（平铺）、Ctrl+Alt+J（下一窗口）。
注册失败会显示提示，按钮仍可使用。启动框接收可执行文件路径；需要参数时用终端或配置。

## WM 协议 `adws.window-policy` v1

传输：独立子进程 stdin 请求／stdout 回复，每行一个 UTF-8 JSON；一次最多一个未完成请求。
每条消息最多 1 MiB；回复期限两秒，涵盖管道写入与读取。stderr 被持续丢弃，避免阻塞和无限日志占用；
本原型尚无模块日志查看器。模块与当前用户同权限，进程隔离不是权限沙箱。
启动失败、EOF、超时、畸形 JSON、超限、版本／序号错误都关闭模块，取消自动平铺，保留宿主与恢复界面。
用户点 Tile 可重新启动模块，不无限自动重启。

请求示意（每台显示器一次，坐标为启用 PerMonitorV2 后的屏幕像素）：

```json
{"api":1,"sequence":42,"type":"layout","capabilities":["enumerate","move-resize","focus-best-effort"],"workArea":{"x":-1920,"y":0,"width":1920,"height":1080},"windows":[{"id":12345,"processId":123,"title":"Editor","bounds":{"x":0,"y":0,"width":800,"height":600},"focused":true}]}
```

回复示意：

```json
{"api":1,"sequence":42,"type":"layout","placements":[{"id":12345,"bounds":{"x":-1920,"y":0,"width":1920,"height":1080}}]}
```

版本、序号、type 必须匹配；只允许请求中已有的 HWND，禁止重复 HWND、非正尺寸、整数溢出和越出工作区。
模块可省略窗口使其保持浮动；可输出重叠矩形实现浮动策略。当前协议只向模块委派布局，焦点由宿主按钮与快捷键控制；
不提供任意运行命令、关闭窗口或修改系统设置的消息。HWND 只在当前快照有效；移动前再次核对 PID 和管理资格。
能力描述实际可用的后端操作，不表示 Windows 会无条件允许聚焦或移动每个窗口。

替换示例：在 `windows-config.json` 配置 `"wm":{"fileName":"C:\\ADWS\\my-wm.exe","arguments":[]}`。
空配置使用系统 x64 dotnet 启动同目录 `Adws.Windows.Wm.dll`。模块需 flush 每条回复，只能在 stdout 输出协议。

## 窗口边界与恢复行为

监听前台变化、创建／销毁／显示／隐藏、移动结束、最小化状态和名称变化，500 ms 合并刷新；
五秒重枚举以修补漏事件。移动期间不订阅持续 location-change，避免平铺反馈风暴。
枚举保留无 owner、可见、非最小化、可调整大小、非 tool/noactivate、非 cloaked 的顶层窗口；
排除桌面／任务栏、宿主自身、最大化窗口及覆盖屏幕的无标题栏窗口。owned dialogs 暂时浮动。
示例 WM 按 HWND 稳定顺序分列，每台显示器分别使用工作区；不跨屏迁移、不伪造工作区。

WinEvent 在带消息循环的 UI 线程安装和解除，回调保持强引用。焦点调用尊重 Windows 的拒绝结果；
不使用输入注入或 AttachThreadInput 绕过限制。管理员窗口、应用最小尺寸、边框、特殊窗口和 DPI 切换仍需兼容性验证。

恢复窗口是独立进程，工作进程每 500 ms 心跳；超过十秒无心跳提示无响应。
恢复界面可停止／手动重启宿主、打开终端或任务管理器；**只有点击 Restore Explorer 才启动 Explorer**。
停止先请求正常关闭，2.5 秒后只终止 ADWS 工作进程，用户应用不随之终止。
WM 被放入 kill-on-close Job Object，宿主崩溃时可清理已纳入 job 的 WM 及其后代。
启动与纳入 job 之间存在小时间窗；本机制不是针对恶意模块的安全隔离。
正常退出尝试恢复已移动窗口的原矩形；崩溃／强制终止时不保证恢复矩形，也不持久化窗口标题。
恢复进程意外退出后，仍响应的工作进程会在下一次 timer tick 自行退出。
恢复进程与工作进程同时挂起时仍依赖系统任务管理器或 VM 控制台，未宣称完全自愈。

## VM 验收清单（尚未执行）

1. 创建 VM 快照、普通测试账户及独立维护管理员账户；保存恢复凭据和 VM 控制台入口。
2. 先在保留 Explorer 的 VM 测试账户运行，启动两三个普通 Win32 测试应用；检查创建、关闭、改名、最小化、焦点循环和逐屏平铺。
3. 检查 owned dialog、tool window、最大化／全屏、权限较高窗口不会被错误强制接管；测试负坐标屏幕、混合 DPI、显示器断连。
4. 用替换 WM 测试超时、崩溃、超大回复和非法 HWND；应停止自动管理，手动重试有效，恢复窗口始终可用。
5. 在任务管理器中仅结束／挂起 VM 内 ADWS 工作进程，观察独立恢复界面；检查终端、任务管理器、重启及手动恢复 Explorer。
   检查正常停止尽可能恢复矩形；用户启动的应用继续运行；WM 没有残留。
6. 完成前述步骤后，才在 VM 内按该版本 Windows 支持的 Shell Launcher 方案为测试账户配置自定义 Shell，入口为完整路径
   `Adws.Windows.Host.exe --test-session`。恢复窗口进程保持常驻，不能把入口换成启动后立即退出的脚本。
   维护管理员账户继续使用 Explorer。此仓库不提供自动注册、修改 Winlogon 或终止 Explorer 的脚本。
7. 重新登录测试账户，确认 Explorer 未启动、DWM 正常、启动／平铺／聚焦／文件管理器／恢复全部可用。
   手动启动 Explorer 只恢复本次会话，不会撤销 Shell Launcher 配置；退出测试需从维护账户撤销测试账户的 Shell 配置，再重新登录验证。
8. 记录 OS 版本、DPI、显示器、应用、步骤与结果；失败时回滚 VM 快照。该记录是进入下一阶段的门槛。

本次真机测试经用户授权，仅管理临时测试窗口。登录 Shell 切换仍留待隔离账户验收。

## 验证记录与依据

2026-11-13：本地 Windows x64，.NET SDK 10.0.404，目标 .NET 8。
12 组检查通过，覆盖 0–200 窗口的负坐标布局、版本／序号／重复 HWND／越界／溢出拒绝、Unicode、参数边界、
framing、真实子进程正常往返／超时／EOF／畸形消息／超限／手动重试／清理。
Host 与 WM Release publish 成功。在 Explorer 已停止的现有会话中，通过 --test-session --smoke 运行：最多两个临时窗口，33 个事件、14 次布局、移动调用失败 0 次、焦点调用成功 14 次。尚未验证重新登录、实际矩形的逐像素一致性或宿主挂起后的交互恢复。
GitHub Actions 工作流只编译和执行进程协议检查，不作为真实 Shell 会话验收。

参考：
- [EnumWindows](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-enumwindows)
- [SetWinEventHook：线程消息循环与生命周期](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setwineventhook)
- [SetForegroundWindow：前台限制](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-setforegroundwindow)
- [Job Objects](https://learn.microsoft.com/windows/win32/procthread/job-objects)
- [Shell Launcher](https://learn.microsoft.com/windows/configuration/shell-launcher/)
- [按账户配置 Shell Launcher](https://learn.microsoft.com/windows/configuration/shell-launcher/configure)
