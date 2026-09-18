# MNWS 1.25 Released — Arch Linux x86_64

解压 `MNWS1.25_for_arch.zip`，进入解压目录并运行 `./install.sh`。
安装包包含三个预构建原生组件，校验 SHA-256 后直接安装，不需要 Rust/Cargo 或 C 编译。
运行依赖仍需安装，缺少时会询问是否补齐；之后选择启动器、命令入口和 Niri 自启。
中文系统显示中文，其余语言显示英文。

安装后保留解压目录，命令软链接依赖其中的源码和语言文件。
`mnws -s` 启动桌面和任务栏，`mnws --update` 检查正式 Release，
`mnws --uninstall` 卸载。支持 CFFI v2 的 Waybar 仍是必要条件。

Extract the archive, enter its directory and run `./install.sh`.
All three native components are prebuilt and verified with SHA-256 before installation.
No Rust/Cargo or C compiler is needed. The installer offers to install missing runtime
dependencies, choose an application launcher, install command links and enable Niri autostart.
Chinese locales use Chinese; all other display languages use English.

Keep the extracted directory: command symlinks depend on its source and language files.
Use `mnws -s` to start both components, `mnws --update` to check stable Releases,
and `mnws --uninstall` to remove MNWS. Waybar with CFFI v2 is still required.

This archive targets Arch Linux x86_64 only. Other systems should use the source
installer. It has been tested on the build host and in isolated tests; a fresh Arch
login/install/uninstall lifecycle has not yet been verified.
