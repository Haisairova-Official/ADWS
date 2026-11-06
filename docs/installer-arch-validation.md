# Arch 隔离安装验收

本记录区分软件包／配置验证、隔离图形会话验证和实机验证。只有在干净 Arch + Niri 实机完成安装、升级、重复安装、卸载和回滚，并通过功能验收后，才能标记“完整支持”。容器测试不能替代显卡、输入法交互、登录管理器和物理多显示器测试。

## 可复现入口

先从 Arch 官方镜像取得 bootstrap 压缩包，核验官方 SHA256 和基于可信 Arch keyring 的签名，再解压到专用目录。不要把宿主 `/` 当作 rootfs。基础环境需要已通过其自身 pacman 安装 Python；脚本不会在宿主安装任何软件。

在 ADWS 源码目录运行：

```sh
python tests/check_install_arch_clean.py --rootfs /path/to/root.x86_64
```

这一步读取当前 `selected_plan('fresh')`、运行时清单、原生／Waybar／Niri 构建清单，并在隔离系统内逐项查询官方软件源。任何未找到的软件包都会使检查失败。若确认允许向该测试 rootfs 安装依赖：

```sh
python tests/check_install_arch_clean.py \
  --rootfs /path/to/root.x86_64 --install-dependencies
```

测试使用 bubblewrap 的独立用户、挂载、进程等命名空间，共享网络仅用于访问软件源。源码只读挂载到 `/opt/adws`；没有绑定宿主 HOME、图形会话套接字、用户 D-Bus、声卡或显卡设备。进程环境重新创建，仅保留容器内 HOME、PATH、语言设置。

默认产物写入 rootfs 同级的 `reports/`，可通过 `--report-dir` 修改：

- `package-audit.json`：分组清单、官方仓库及软件包版本、缺失项。
- `package-audit.stdout`／`.stderr`：完整原始审计输出。
- `dependency-install.log`：隔离系统内 pacman 输出。
- `dependency-install-result.json`：退出状态与日志位置。

入口不会运行 `install.sh`、启动 ADWS 或修改宿主服务。安装依赖后，可以单独启用隔离图形冒烟测试：

```sh
python tests/check_install_arch_clean.py --rootfs /path/to/root.x86_64 \
  --nested-smoke --report-dir /path/to/reports/nested
```

这一步只在容器内启动私有 D-Bus、Xvfb、使用软件渲染的嵌套 Niri 和一个 GTK 测试窗口，通过 Niri IPC 确认窗口存在，再实际截图并解码。不会绑定宿主屏幕或输入设备。日志和结构化结果分别保存在 `nested-*.log`、`nested-smoke.json` 及标准输出／错误文件中。ADWS 安装生命周期验收仍需另外完成，不由这些检查推断成功。

## 2026-11-06 已取得的证据

- 官方 bootstrap：`archlinux-bootstrap-2026.11.01-x86_64.tar.zst`。
- SHA256：`655bc99849b80859173fa39338a6c910185e952173f6a1a61526cfa34ab8339c`；执行前已完成官方校验与签名验证。
- 初始 rootfs 只有基础系统及 Python，没有继承开发机的桌面依赖和用户配置。
- 新装、原生构建、Waybar 构建、Niri 构建及隔离图形测试共 **70 个去重软件包**全部在官方仓库解析成功，其中新装清单包含 41 个包。
- 这 70 个直接依赖随后已在隔离 rootfs 内安装成功，pacman 退出码为 0；下载约 875 MiB，新增约 3.5 GiB。完整输出保存在 `dependency-install.log`。
- 安装后的真实运行依赖检查通过：`adws_runtime_dependencies.missing_dependencies()` 返回 `{}`，`adws_health.dependency_errors()` 返回 `[]`；检查包含 Gtk/Gst/GstApp 导入及所需 GStreamer 元素。记录位于 `runtime-readiness.stdout`／`.stderr`，它仍不等于窗口预览功能验收通过。
- 查询时官方仓库提供 Niri `26.04-1`、Waybar `0.15.0-3`、Matugen `4.2.0-1`。这些记录只是当时的仓库结果；每次执行仍重新查询。

- 集成后的 `--mode fresh --plan --build-fallback` 在隔离系统中退出码为 0，安装阻塞项、会话环境冲突、自启动未知项和重复归属均为空。
- 默认 Niri 配置通过官方 Niri 的真实校验，没有跳过功能或配置冲突。
- 隔离嵌套图形测试通过：真实 Niri IPC 返回输出与 GTK 测试窗口，`grim` 实际截图成功，Pillow 解码尺寸为 1280 × 800。采用软件渲染；这只是基础图形链路，不是 ADWS 窗口预览验收。

## 尚不可据此认定通过

- 真实普通用户登录、systemd 作为 PID 1 的服务生命周期。
- 显卡驱动、实际显示输出、刷新率、缩放、HDR、亮度硬件控制。
- Fcitx 候选框及 GTK／Qt／XWayland 实际中文输入。
- 窗口预览内容、桌面截图、剪贴板恢复及默认应用启动。
- 普通用户登录后的升级、卸载、回滚和完整功能验收；下文的隔离安装结果只覆盖用户空间配置与文件部署。

后续测试应逐项记录所用环境、实际命令、退出状态和生成报告；待验证项继续标为待验证，不能把隔离用户空间结果升级为实机通过。

官方基准来源：[Arch 下载与校验说明](https://archlinux.org/download/)。

## 隔离构建原生组件

依赖安装完成后，使用独立快照构建，避免开发目录继续修改影响本次构建：

```sh
python tests/build_install_arch_native.py --rootfs /path/to/root.x86_64
```

构建器在 rootfs 同级的 `native-builds/<时间>/` 创建快照。容器只将这个快照可写挂载到 `/opt/adws`，开发目录不会进入此次容器。Cargo 固定 `--jobs 2`，C 组件使用 `make -j2`。默认使用官方 Cargo 源，不读取宿主 Cargo 配置或缓存。

构建输出包含：

- `snapshot-provenance.json` 和 `snapshot-inputs.json`：快照来源与输入文件哈希。
- `native-build.log`／`native-build-result.json`：完整构建日志与结果。
- `prebuilt/libniri_taskbar.so`、`libadws_panel.so`、`libwaybar-space.so`、`adws-plugin-runner`、`adws-start-menu`。
- `prebuilt/manifest.json`：平台、版本和上述五个产物的 SHA256，格式兼容安装器。
- `native-link-checks.json`：各 ELF 的实际动态库解析结果。
- `libexec/` 中两个可执行程序的副本，供之后独立的安装生命周期测试使用。

如果下载或构建失败，可以针对同一个独立快照续建：

```sh
python tests/build_install_arch_native.py --rootfs /path/to/root.x86_64 \
  --resume-snapshot /path/to/native-builds/时间
```

这个入口仍不会运行安装器或启停宿主服务。后续应把产物与经过审核的完整安装源码快照组合后，再执行全新安装、重复安装、失败回滚和卸载案例；本构建结果不替代这些案例。

2026-11-06 的独立原生快照 `20261106-114130` 已实际构建成功，五项产物的动态库检查全部通过。任务栏与开始菜单的 release 构建分别约 108 秒和 60 秒；构建没有读取宿主 Cargo 缓存，也没有增加并行度。

## 真实安装生命周期入口

完成原生构建后，把当时的完整开发源码复制为另一个独立快照，再合并经过输入哈希校验的五项原生产物：

```sh
python tests/check_install_arch_lifecycle.py --rootfs /path/to/root.x86_64 \
  --native-snapshot /path/to/native-builds/时间
```

测试在容器内使用独立 HOME，真实执行主流程的只读计划生成、测试计划批准、安装、同计划续装和重新规划后的重复安装；包管理器、服务链接、配置写入与原生组件部署不使用模拟。安装结果为“待图形验收”时，产品退出码 2 会保留在证据中，不能当作完整通过。

产物位于 rootfs 同级 `installer-cases/<时间>/`：`lifecycle.log`、`lifecycle-evidence/result.json`、每次执行的计划／进度／备份索引。任一案例失败会停止后续案例，保留现场等待修复，不自动跳过。

首轮真实安装发现了单元测试未覆盖的阻塞：干净 PATH 不含 `~/.local/bin` 时，旧命令安装器仍在中途询问是否写入 `/usr/local/bin`，无输入时以 130 取消。此前原生组件和符号字体已实际部署成功；失败后 Niri、默认终端、Waybar 配置、本地原生库和用户服务链接均回滚，软件包仍保留。该失败记录用于修正集中安装选项，不能作为安装通过证据。

随后真实重复安装发现，自启动命令未变化但 Niri 行号移动，会被误判成“归属变化”。修正稳定身份比较后，独立快照 `20261106-115557`、`20261106-120017`、`20261106-120415` 的全新安装、同计划续装和重新规划后的重复安装都完成配置部署，三次产品退出码均为 **2：待功能验收**。

需要复现失败后的续装时：

```sh
python tests/check_install_arch_lifecycle.py --rootfs /path/to/root.x86_64 \
  --native-snapshot /path/to/native-builds/时间 --failure-resume
```

该选项仅在独立快照的配置脚本末尾增加一次性退出码 23，记录于 `validation-injection.json`；产品源码不变。包管理、原生组件和配置部署仍真实执行。脚本检查 Niri、原生库和符号字体恢复，日志与已完成的软件包步骤保留，再用同一审核计划续装。原始计划或源码变化仍应要求重新审核。

## 已安装组件的隔离图形检查

```sh
python tests/check_install_arch_session.py --rootfs /path/to/root.x86_64 \
  --installer-snapshot /path/to/installer-cases/时间
```

这个检查使用已安装 fixture 的 HOME 和 Niri 配置。任务栏通过真实 `spawn-at-startup` 启动，检查加载原生库的唯一底栏、Niri IPC、真实 GTK 窗口、截图和剪贴板文本经 cliphist 存取后的内容一致性。截图与日志保存在 `session-evidence/`。

`20261106-120017` 的上述任务栏、GTK、截图和剪贴板底层存取已实际通过。桌面图标进程直接启动后也正常初始化。容器没有 systemd 用户管理器，因此桌面的独立用户服务启动仍为 **待验证**；直接运行进程不替代服务验收。ADWS 剪贴板 UI 选择／粘贴、窗口 Peek 画面、默认应用启动仍保留在产品验收的待验证列表。

首次图形试验还暴露了测试环境自身的限制：系统 glycin 图像加载器需要再创建用户命名空间，内层 bubblewrap 报 `setting up uid map: Operation not permitted`，导致普通 GTK 窗口与 Waybar 同时加载 SVG 失败。会话 harness 现在仅在测试的外层用户命名空间保留 UID/GID 映射及 `CAP_SETFCAP`，实测内层 bubblewrap 可正常运行；没有关闭 glycin 自身隔离，没有增加宿主权限，也没有修改 ADWS 的图像加载行为。

## 卸载范围检查

完成图形检查后再运行卸载，因为它会实际移除该 fixture 的 ADWS 文件：

```sh
python tests/check_install_arch_uninstall.py --rootfs /path/to/root.x86_64 \
  --installer-snapshot /path/to/installer-cases/时间
```

该入口只接受 `installer-cases` 下的独立快照。它额外创建明确记录的测试显示配置和配色引用，执行真实的“卸载并删除组件配置”，确认 ADWS 自启动／命令链接／原生库消失，共享启动、默认关联、配色和 Niri 引用仍保留，并重新调用真实 Niri 校验。

实际检查发现并修正了两项卸载问题：新的统一自启动块未清除 ADWS 启动命令，以及删除整个 ADWS 配置目录会使 Niri 的会话环境 include 悬空。卸载保留系统键位和安装源码；没有逐绑定的所有权记录时，不按命令名称全局删除用户快捷键。

## 最终组合复测

2026-11-06 冻结后的组合快照 `20261106-121049` 实际结果如下：

| 案例 | 结果 |
| --- | --- |
| 全新安装 | 配置部署完成；产品退出码 2，待交互验收 |
| 同计划续装 | 复查后完成；退出码 2 |
| 重新生成计划后重复安装 | 完成；退出码 2 |
| 隔离图形会话 | 任务栏原生组件、IPC、GTK 窗口、截图、剪贴板存取通过 |
| 桌面进程 | 直接运行、D-Bus 就绪和短时稳定检查通过；用户服务仍待实机验收 |
| 删除组件配置的真实卸载 | 命令／库／ADWS 启动被移除；共享启动、默认应用、配色和额外显示 include 保留 |
| 卸载后 Niri 校验 | 退出码 0 |

同一冻结版本的故障注入快照 `20261106-121154` 在真实配置脚本末尾退出 23 后，确认 Niri、本地原生库和符号字体目录回滚，持久进度和软件包步骤保留。之后使用 **同一个审核计划**续装成功，重复检查和重新规划后的安装也成功；图形验收仍返回待验证，而非误报完成。

这些结果证明已覆盖隔离用户空间中的安装、重复执行、失败恢复和卸载范围；不把它们写成普通用户登录、物理 GPU、多显示器或完整 Arch 实机支持已经通过。每个快照中的 `snapshot-inputs.json` 保留实际测试源码哈希，故障注入另外留有明确标记。

## 最终 TEST 副本与新增 Fcitx 启动项

在包含安装来源选择、受管旧配置迁移及包启动项审核的最终 `/home/akizuki/MNWS` 副本上，再次建立独立测试 rootfs，未修改供虚拟机使用的共享 rootfs。仅在这个副本中通过真实 pacman 移除 Fcitx 相关包，确认 `fcitx5` 二进制和标准系统 XDG 启动文件都不存在，再执行实际安装。

- `arch-package-transition-20261106/installer-cases/20261106-124140`：真实包安装创建标准 XDG 入口；已审核的用户 Hidden 影子文件生成，最后只有一个 Niri 输入法启动归属。全新安装、续装、重复安装均退出 2，保留待验收状态。
- 同一快照的图形测试通过。ADWS 的真实默认终端解析接口选择 `foot.desktop` 并启动 `/usr/bin/foot`，Niri 确认对应 PID 窗口；不再选到只运行后台服务的 Foot Server。
- `session-evidence/installed-session.png` 同屏展示真实底栏、实际默认终端，以及直接读取本轮 `reinstall/result.json` 的测试报告窗口。报告窗口是验收展示，不是新增的 ADWS 产品界面；仍显示原始无图形安装时记录的待验收状态。
- 仅临时测试会话配置关闭 Niri 首次热键提示，安装配置保持不变。实际生成 KDL 包含 `Mod+Z` 菜单、`Mod+Alt+Comma` 设置及 `Mod+Alt+L` 锁屏；嵌套 Niri 的 Mod 映射为 Alt，截图提示不能用来推断普通会话里的 Super 键配置。
- 该快照的真实卸载与卸载后 Niri 校验均通过，额外显示 include、配色、默认关联和共享启动保留。
- 再次仅在副本中移除 Fcitx 后，`20261106-124350` 从同样的无入口状态执行故障注入：真实装包、创建受管影子、配置结束后退出 23；配置／本地库／字体恢复，软件包步骤与进度保留。同一个审核计划随后续装成功，最终输入法归属仍唯一；重复安装也成功。

`124140` 审核计划记录的源码指纹为 `cab8ea9553f62b69f3e9c208d1fa7c37934d849913001d1b7c2bfbc130280a6d`。这一轮仍属于无宿主 GPU 和输入设备绑定的 root-mapped 用户空间测试，普通用户登录与物理硬件验收边界没有改变。

## 实际菜单与剪贴板交互

随后使用 `124350` 快照的隔离用户空间会话（UID 1000、官方 Niri 26.04、Xvfb/llvmpipe）实际点击开始按钮、菜单应用和剪贴板历史项目。原始报告在 `arch-package-transition-20261106/graphical-interactions/interaction-report.json`：

- 开始按钮打开真实原生菜单；点击 Foot 项目后，Niri IPC 确认新终端窗口。
- 底栏载入原生组件，并显示该窗口的应用图标。
- 先后写入两条剪贴板内容；点击历史中的旧项目后，`wl-paste` 读回旧内容，区别于点击前的新内容。
- 在仅属于测试副本的设置中开启 Peek，确认悬停卡片及 Niri 的 RecordWindow/Start 请求。Niri 随后报 `no GBM device available`，因此**真实预览画面仍待验证**；不能用卡片出现代替画面捕获通过。

该环境未接入宿主剪贴板、输入设备或 GPU；没有正常登录的用户服务管理器。已结束测试会话，没有改动生产配置。截图见 [进度与截图报告](installer-progress-2026-11-06.md)。
