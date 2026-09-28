# ADWS modifier-taps 1.0.0 / 可选单修饰键补丁

此补丁只针对官方 **Niri v26.04**，固定提交为
`8ed0da44d974c32c6877d2f4630c314da0717ecb`。它是 ADWS 维护的下游补丁，尚未提交或合入上游。
`niri --version` 显示 `ADWS modifier-taps 1.0.0`；补丁版本独立于 ADWS 主版本。
校验值见 `manifest.json`；其他版本及有本地改动的源码拒绝应用。

增加单独轻按并松开 Super/Ctrl/Mod 等修饰键的绑定支持。原有按下和松开事件继续送到应用；
按住其他键、再按另一个键、重复按下、鼠标点击/滚动或触控操作都会取消待执行的轻按。
动作遵循原有锁屏、快捷键抑制和冷却限制，不自动设置任何键位，不改变渲染和桌面布局。
只支持独立修饰键轻按；不提供双击、长按或修饰键连击功能。

## 使用

```sh
adws niri-compat status
adws niri-compat build
# 或：使用固定版本的干净源码（工具会复制，不在原目录打补丁）
adws niri-compat build --source /path/to/niri --jobs 2
```

构建需用户确认，默认取消，默认使用两个编译任务。需要 Git、Rust/Cargo、C 编译器、pkg-config
以及 [Niri 官方构建依赖](https://niri-wm.github.io/niri/Getting-Started.html#building)。缺少依赖时先补齐再重试。
工具下载源码，核对提交与补丁 SHA-256，通过 `git apply --check` 后应用，运行修饰键测试，再构建 release。
产物位于 `$XDG_CACHE_HOME/adws/niri-compat/build-*/bundle`（默认 `~/.cache`），保留源码和上游许可证。

工具会打印产物路径与可选安装命令：

```sh
adws niri-compat install --bundle /path/to/bundle
```

安装后独立入口是 `~/.local/bin/niri-adws`。系统 `niri`、`niri-session`、服务和登录管理器不变。
在现有图形会话运行 `niri-adws` 可打开嵌套测试窗口；先使用适合官方 Niri 的测试配置，
不要直接套用其他分支专有配置。确认可用后，退出原桌面，在 TTY 执行 `niri-adws --session`。
它不会自动注册登录管理器条目；系统门户、锁屏与登录集成仍使用原有系统配置。

只有启动兼容版会话后才能在 ADWS 设置中应用三档键位。独立启动器通过 `ADWS_NIRI_BINARY`
让子进程使用正确的配置校验程序，仅安装二进制不会把正在运行的标准版变成兼容版。

## 恢复

先在兼容会话中执行：

```sh
adws niri-compat restore
```

它只删除 ADWS 键位管理块，保留你原先的绑定及其他 Niri 设置。退出兼容会话后，选择原来的
Niri 登录项或运行原来的 `niri-session` 即可。需要移除可选二进制时，在恢复原版之后删除
`~/.local/bin/niri-adws` 以及仅供此功能使用的 `~/.local/lib/adws-niri/`；构建缓存可另外清理。

## English

`niri --version` identifies the patch as **ADWS modifier-taps 1.0.0**. The patch has its own version, separate from ADWS itself.

This optional downstream patch targets only upstream **v26.04**, commit
`8ed0da44d974c32c6877d2f4630c314da0717ecb`. It has not been submitted to or merged upstream.
It adds standalone modifier taps, preserving client press/release events and cancelling taps on
other keyboard, pointer and touch interactions. Existing lock, shortcut-inhibition and cooldown
policies remain in force. It changes neither default bindings nor rendering. Double taps and
modifier chords are outside this patch's scope.

`adws niri-compat build` asks before downloading/building. `--source` accepts a clean checkout of
the pinned revision and clones it before patching; `--jobs` defaults to 2. Source revision, patch
integrity, clean application, focused tests and a release build must pass. The optional `install
--bundle` action verifies binary integrity and creates **niri-adws**, leaving system **niri**,
services and the login manager intact. The wrapper selects its own validator for ADWS child apps.

Test nested first with an upstream-compatible config. After exiting the original desktop, use
`niri-adws --session` from a TTY. No display-manager entry is installed automatically. Run
`adws niri-compat restore` before returning to the original login entry; this removes only ADWS's
managed keyboard override. Optional binaries and build caches can then be removed separately.

## Attribution

Niri is copyright Ivan Molodetskikh and contributors, GPL-3.0-or-later. The modifier-name parser
adaptation comes from [SHORiN-KiWATA/niri at 21be84f6](https://github.com/SHORiN-KiWATA/niri/tree/21be84f6),
under the same license. The ADWS standalone-tap state machine, integration, tests and build tooling
are GPL-3.0-or-later. Upstream LICENSE is preserved in built bundles.
