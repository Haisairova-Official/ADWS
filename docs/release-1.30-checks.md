# ADWS 1.30 stable release checks / 稳定版发布检查

构建日期 / Build date: 2026-09-28. 发布分支 / Release branch: `Pre-1.30`; tag: `v1.30`.

- [x] 版本统一为 `1.30 Released`；help、README、CHANGELOG 和 Release Notes 使用相同的 30 条中英文累计记录。
- [x] 215 项 Python 测试通过，包含安装、更新、迁移、插件、配置恢复和语言覆盖。
- [x] Rust 6 项核心测试及 6 项独立 GTK 测试通过：Peek、固定应用、窗口排列、弹窗事件、配色与预览取消。
- [x] C 组件 3 组测试通过：面板、鼠标交叉事件与宽度过渡、竖排歌词及图片尺寸。
- [x] 8 组设置界面检查分别在中文和英文环境通过，共 16 次；初始向导刷新失败、保存恢复错误另有 2 次检查通过。
- [x] Python 编译、安装脚本语法检查通过，Rust release 构建成功。
- [x] 用户反馈日常使用测试已基本完成。
- [x] 完整更新记录已经用户确认；发布到 `Pre-1.30`，主分支由用户合并。

## 包验证 / Archive verification

准备 `ADWS1.30_for_arch.zip` 和 `ADWS1.30_source.zip`，各附 `.sha256` 文件。生成后检查 ZIP 完整性、版本与中英文帮助、内置 niri-ipc 和新增恢复工具是否齐全、运行状态及构建缓存是否被排除。Arch 包另检查原生库哈希、当前构建主机上的动态依赖，并将预构建组件实际安装到临时目录。包校验结果保存在附件目录中的 `archive-validation.json`。

The two archives have SHA-256 sidecars. Post-build validation checks ZIP integrity, version and bilingual help, vendored niri-ipc, newly added recovery tools, and excluded runtime/build data. The Arch archive additionally checks native-library hashes and dynamic dependencies on the build host, then installs the actual prebuilt libraries into a temporary directory. Results are saved alongside the archives in `archive-validation.json`.

## 验证边界 / Limits

所有界面测试使用独立虚拟显示器与临时配置，不操作真实桌面。尚未完成所有发行版或新设备的完整登录、安装、升级、卸载生命周期；旧静置卡顿的根因仍未完全确认。文件恢复不等同于断电自动恢复；已经通过系统包管理器安装的软件包不在回滚范围内。

GUI checks use isolated displays and temporary configuration. Fresh-machine full lifecycle coverage is incomplete, and the earlier idle-stall root cause remains unconfirmed. File rollback is not power-loss recovery; installed system packages are outside its scope.
