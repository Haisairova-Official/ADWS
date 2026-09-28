# 安装详情 / Installation details

### 构建与安装

1.30 稳定版发布后，可从 `v1.30` 标签安装源码版。安装程序会询问是否补齐缺失依赖，增量构建三个原生组件，备份文件并停止旧组件后完成安装；后续失败时尝试恢复原文件和原先运行的组件。系统包管理器已经安装的软件包不在恢复范围内。

```sh
git clone --branch v1.30 https://github.com/Haisairova-Official/ADWS.git ADWS
cd ADWS
./install.sh
adws -s
```

Arch Linux x86_64 用户可使用 `ADWS1.30_for_arch.zip`，解压到固定目录后同样运行 `./install.sh`。预构建包会校验并安装原生组件，无需现场编译 Rust/C；运行依赖仍需要安装。

For the stable source release, use the `v1.30` tag and run `./install.sh`. The installer offers missing dependencies, incrementally builds native components, backs up integration files and stops old components before replacing files. Later failures attempt to restore files and previously running components; packages already installed through the system package manager are not rolled back. Arch Linux x86_64 users can use the prebuilt ZIP with the same installer.

仓库根目录的 `./install.sh` 与 `./adws install` 使用相同安装流程。

`adws install` 会先检查运行依赖；缺失时询问是否补齐，拒绝或失败时停止。源码版始终检查并增量构建原生组件，不会仅凭旧动态库存在就跳过构建。
预检通过后，将启动器链接到 `~/.local/bin`，向 `$XDG_CONFIG_HOME/waybar`（默认 `~/.config/waybar`）复制缺失的默认配置。
已有配置文件和有效符号链接均保留，不导入或覆盖源码中的默认配置；遇到失效链接会停止并提示修复。
安装会创建缺失的桌面目录，优先使用桌面配置或 XDG 桌面目录，否则使用 `~/Desktop`。
如果使用已有共享配置，请确保它定义了 `custom/applauncher`、`niri/workspaces` 和 `clock`。
安装后应保留仓库目录（命令入口仍链接到源码），并把 `~/.local/bin` 加入 `PATH`。
`adws build-taskbar` 默认允许下载依赖，并原子替换编译后的动态库；新模块在下次启动任务栏时加载。
`adws check` 检查依赖、配置引用、启用的动态库与桌面目录，检查失败返回非零状态。
`adws layout apply` 在写入前验证配置；任务栏启动后立即退出时会返回失败。
后台任务栏日志保存在 `$XDG_STATE_HOME/adws/taskbar.log`（默认 `~/.local/state/adws/taskbar.log`）。

将 [config/adws-windows.kdl](../config/adws-windows.kdl) 中的窗口规则加入 Niri 配置，使设置窗口浮动。
用 `niri validate` 检查配置。启动桌面图标层：

```sh
adws desktop --start  # 或 adws desktop -s
./adws autostart on
```

第二条命令开启桌面图标层登录自启；任务栏自启需加入你自己的会话启动配置。


### Build and install

This is a source integration project. The installer offers to install missing dependencies and build missing components after confirmation, with apt, pacman and dnf support.
Back up your Waybar configuration, install the dependencies above, then run the build and installation commands in the [Chinese section](#构建与安装) from the repository root.
For an existing installation, stop the bottom Waybar before replacing its loaded shared libraries.

Run `./install.sh` from the repository root, or use the equivalent `./adws install`.

`adws install` checks dependencies and libraries, offers to repair missing items, and stops if declined or unsuccessful.
It links launchers into `~/.local/bin` and copies missing defaults into `$XDG_CONFIG_HOME/waybar` (default: `~/.config/waybar`).
Existing files and valid symlinks are preserved; broken configuration symlinks cause installation to stop.
The installer initializes the configured/XDG desktop directory, falling back to `~/Desktop`.
If keeping existing shared configuration, make sure it defines `custom/applauncher`, `niri/workspaces` and `clock`.
Keep the checkout after installation (launchers still link to the source) and add `~/.local/bin` to your `PATH`.
`adws build-taskbar` permits dependency downloads and replaces the built library atomically; restart the taskbar to load it.
`adws check` validates dependencies, configuration references, enabled libraries and the desktop directory, returning nonzero on failure.
Layout application validates before writing. Early taskbar exit reports failure and retains output in `$XDG_STATE_HOME/adws/taskbar.log` (default: `~/.local/state/adws/taskbar.log`).

Add the rules in [config/adws-windows.kdl](../config/adws-windows.kdl) to your Niri configuration to make settings windows float, then check with `niri validate`.
Start the desktop icon layer with `adws desktop --start` (or `adws desktop -s`).
Use `./adws autostart on` to enable desktop-icon autostart; add taskbar startup to your own session configuration separately.

