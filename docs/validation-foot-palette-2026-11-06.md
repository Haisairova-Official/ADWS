# Foot 配色的真实隔离验证（2026-11-06）

本次使用已安装 Foot 1.28.0 的 Arch 根文件系统，实际启动 Foot、Bash 和嵌套 Niri。根文件系统及 ADWS 产品目录均只读；HOME、PID、D-Bus、网络、X11、Wayland 和运行目录隔离，使用软件渲染。没有安装宿主软件、连接宿主会话或扫描其他终端，也没有改动根文件系统的软件包清单。

证据保存在 `/home/akizuki/.local/state/adws/validation/foot-palette/`。最终通过记录为 `run-07/result.json`，截图为 `run-07/before.png` 和 `run-07/after.png`；相关单元测试记录为 `unit-tests.log`。

## 发现和修复

1. **新 Foot 拒绝旧颜色节。** 原生成片段使用 `[colors]`；真实 Foot 1.28.0 的 `--check-config` 返回 230，提示该节无效。旧版本与新版不能统一写死同一节名。
2. **控制终端设备所有者判断错误。** `/dev/tty` 是内核的当前控制终端入口，其设备节点由系统拥有，不能用节点 UID 判断当前用户是否拥有终端。原 helper 在真实 Foot 启动时直接退出；只传入 PTY 从端的单元测试未覆盖此情况。
3. **另一个终端继承旧 helper PID。** 新 Foot 从已有终端启动时会继承环境，原逻辑可能误以为已有本终端 helper。现在仅在自身终端标识与存活 helper 一致时复用。获取标识使用本终端文件描述符，避免命令替换的输出管道被当作终端。
4. **关闭时的清理。** helper 在 SIGHUP、SIGTERM 或父 shell 结束时退出并移除自身注册文件。

## 格式选择与安装事务

`registration_plan()` 不要求 Foot 已经安装。计划展示 `[colors-dark]` 与旧 `[colors]` 两份等价色值片段，并明确采用 `foot_format_policy="auto"`。

依赖安装后，`register()` 调用 `resolve_foot_plan()`，通过实际安装的 `foot --check-config` 选择可用格式。它检查完整的拟写入主配置及临时颜色片段；保留其他绝对路径和 `~/` 引入，不执行终端、shell 或用户命令。两种格式都失败时，停止注册，保留所有用户文件，不留下已应用一半的其他配色目标。

解析过程只改变计划中颜色片段的节名，不重新生成其他用户文件。最终选中格式及验证结果写入注册记录和返回结果。后续配色刷新沿用该格式；未记录解析格式的旧注册会报告需要重新注册，避免继续生成未知格式。真实写入仍在原注册备份及外层安装事务内。

## 最终结果

| 检查 | 结果 |
| --- | --- |
| 实际 Foot 1.28.0 完整配置校验 | 退出码 0 |
| 第一终端实时背景色 | OSC 11 查询由 `#202128` 变为 `#315a72` |
| 第二终端继承第一终端的 helper PID 与 TTY 环境 | 建立独立 helper，同样实时变色 |
| 实际渲染截图 | 变更前 425,389 个像素匹配旧背景，变更后 850,822 个像素匹配新背景 |
| 关闭两个终端 | Foot 均正常退出，helper 进程和注册文件均归零 |
| 无终端时再次刷新 | 报告 `hook-activation-pending`，没有伪造活动终端 |
| 配色与壁纸回归测试 | 26 + 2 项通过 |

`run-02` 保存原始配置失败；`run-04` 保存控制终端判断失败；`run-06` 保存完整继承环境下发现的标识错误。`run-03`、`run-04` 的旧格式替换仅用于诊断夹具，不能计作产品通过。最终 `run-07` 没有使用诊断替换。

本次验证 Bash、Foot 1.28.0 与隔离软件渲染环境。旧 Foot 格式选择使用模拟旧解析器的回归测试覆盖，没有宣称已实际运行旧版 Foot；真实硬件、普通用户完整登录、其他终端及长期运行仍有各自的验收范围。

## 重复验证

```sh
python tests/check_palette_foot.py \
  --rootfs /path/to/verified/arch/root.x86_64 \
  --report-dir /path/to/new/foot-evidence
```

要求目标根文件系统已经安装 Foot、Niri、Xvfb、D-Bus、grim、Pillow 和 Bash；脚本不安装依赖。报告目录必须不存在，避免覆盖旧证据。

依据：[Foot 配置格式与 include 规则](https://man.archlinux.org/man/foot.ini.5.en)、[Foot `--check-config` 的退出状态](https://man.archlinux.org/man/foot.1.en)、[Foot OSC 控制序列](https://man.archlinux.org/man/foot-ctlseqs.7.en)。
