# 平台支持与发布验收

这份标准适用于安装器改进后的发布。实现了兼容代码、单元测试通过、开发机运行正常，都不能直接标为“完整支持”。支持声明必须对应一个确定的发布包 SHA-256 和该包的验收报告。

## 当前支持声明

| 平台 | 当前说明 | 完整支持条件 |
| --- | --- | --- |
| Arch Linux x86_64 + Niri | 主要交付目标；现有开发机回归不等于全新系统验收 | 本文全部矩阵在干净 Arch 实机完成并审核 |
| Arch 用户空间容器 / chroot | 可检查包依赖、安装文件及部分配置行为 | 不能代表图形会话、显卡或实机安装验证 |
| Arch 虚拟机 + Niri | 已有普通用户首次安装、重启及嵌套 GUI 的分项证据；简化虚拟 GPU 不支持本次直接 DRM 输出 | 虚拟显卡结果不能取代实机证据 |
| Ubuntu / Mint / 其他发行版 | 按具体产物的兼容性报告列出通过项与限制 | 尚不授予 Arch 的完整支持标记 |
| 其他桌面环境 | 暂缓扩大适配范围 | 先完成 Niri 安装、设置、更新和迁移 |

这里没有为当前开发中的版本预先授予完整支持。发布时应附上实际测试过的 Niri 版本、官方/分支标识、GPU、驱动、显示器数量和缩放情况；不要将一台机器的结果扩展成全部硬件组合均已验证。

2026-11-06 的实测进展与截图见 [安装器进度报告](installer-progress-2026-11-06.md)。各轮源码快照分别记录，后续修复不能追认到先前已完成的测试里；发布包冻结后仍须按其最终哈希验收。

## 必需矩阵

每一项都要记录实际观察、环境、被测发布包、日志或截图。失败、受阻、未测及缺少审核的项目不会计入完成。

| ID | 验收操作 | 应保留的证据 |
| --- | --- | --- |
| `install.fresh` | 干净 Arch + Niri 首次安装，完成默认应用、会话组件与功能验收 | 安装计划、完整日志、结果报告与备份目录 |
| `install.upgrade` | 从明确的旧版产物升级，检查个人修改和文件关联 | 新旧产物哈希、升级日志、升级前后差异 |
| `install.reinstall` | 同版本重复安装 | 无重复自启、配置未被反复覆盖的对照 |
| `install.uninstall` | 选择删除 ADWS 配置后卸载 | ADWS 项清理、系统配置仍保留的对照 |
| `install.rollback` | 注入一次可恢复安装失败并回滚 | 基线产物哈希、备份清单、失败日志、恢复后对照 |
| `feature.preview` | 打开真实窗口并悬停显示预览 | 预览内容、失败提示与相关日志 |
| `feature.screenshot` | 实际截取选区及屏幕 | 生成的图片、剪贴板结果或命令日志 |
| `feature.clipboard` | 跨应用复制并粘贴文本/图片，打开剪贴板面板 | 原始内容与粘贴结果 |
| `feature.launch` | 从默认快捷键、开始菜单、文件关联启动所选应用 | 真实启动结果与进程/窗口记录 |
| `feature.taskbar` | 启动、隐藏、显示、聚焦、关闭窗口和托盘操作 | 栏及窗口状态的实际变化 |
| `state.tiled` | 平铺窗口切换、最大化与任务栏吸附变化 | 前后画面与日志 |
| `state.floating` | 浮动窗口切换、设置窗口及菜单 | 几何、圆角与输入状态 |
| `state.empty_workspace` | 空工作区和有窗口工作区间切换 | 栏显示、吸附与组件状态 |
| `state.multi_monitor` | 至少两块显示器，切换焦点与指针所在屏幕 | 屏幕标识、缩放、主屏与弹窗位置 |
| `state.docked` | 触发任务栏吸附 | 外侧圆角/边距、内部角和菜单独立样式 |
| `state.undocked` | 从吸附恢复悬浮 | 位置、间距、圆角与动画结束状态 |
| `state.theme_switch` | 切换壁纸取色/主题 | 任务栏、默认图标、菜单、终端、通知刷新结果 |

升级和回滚必须指出不同于待发布包的基线产物；多显示器必须登记不少于两块屏幕。各项可以附多份证明文件，原始文件会复制进入证据目录并保存 SHA-256。

## 记录与审核

以下命令只记录证据或检查证据，不安装系统、不自动为测试结果背书。将示例路径、硬件与人员替换为实际值。

```sh
python3 tools/adws_install_validation.py --record install.fresh \
  --directory ./release-evidence --artifact ./ADWS-release.zip \
  --status passed --environment physical --distro arch --clean \
  --niri-version '实际 niri --version 输出' \
  --hardware '实际 GPU、驱动及显示器描述' --displays 2 \
  --tester '实际验收人员' --notes '实际观察及安装方式' \
  --proof ./installation.log --proof ./installation-result.json
```

`--status passed` 只是验收人员的观察记录。审核人员还需检查附件与步骤是否一致，再对该记录明确确认：

```sh
python3 tools/adws_install_validation.py \
  --review ./release-evidence/记录ID/evidence.json \
  --directory ./release-evidence --reviewer '实际审核人员' \
  --notes '审阅了哪些证据、确认了哪些结果'
```

审核记录绑定证据 JSON 的哈希；之后修改观察或附件会使审核失效。自动化记录不能通过这一步伪装成人工实机验收。

```sh
python3 tools/adws_install_validation.py --check \
  --directory ./release-evidence --artifact ./ADWS-release.zip
```

这会生成 `support-report.json`，列出所有缺失、失败、未审核、产物不匹配及附件变化，并附报告摘要哈希。只有全部 17 项都有当前产物对应的、已审核的干净 Arch 实机人工证据，`complete_support` 才为 `true`，退出码才是 0；其他情况退出码为 2。相同项目出现较新的失败记录时，旧的成功记录不能掩盖它。

## 隔离图形回归

已有真实输入回归可通过统一入口在临时 HOME/XDG 目录、私有 D-Bus、Xvfb 和嵌套 Niri 中运行，不向当前桌面发送输入：

```sh
# 先在源码目录构建测试程序；不会安装组件。
cargo test --offline --manifest-path src/niri-taskbar/Cargo.toml --lib --no-run
python3 tools/adws_install_validation.py --run-nested tray \
  --directory ./release-evidence --artifact ./ADWS-release.zip
python3 tools/adws_install_validation.py --run-nested shift \
  --directory ./release-evidence --artifact ./ADWS-release.zip
```

入口会检查工具和已编译测试程序；缺少依赖会记录 `blocked`，实际测试非零退出或超时会记录 `failed`，成功才记录 `passed`。这些记录的来源始终是 `automated/nested`，只作补充回归，不会填补 17 项实机矩阵。运行的源码及测试程序也应对应被测发布包，不能将另一个工作区的结果当作该发布包的完整验收。

`tests/check_install_arch_clean.py` 提供另外的干净用户空间检查。容器、嵌套图形回归与实机矩阵各自保留自己的环境等级，不互相冒充。
