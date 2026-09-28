# Reliability fixes — 2026-09-22 / 可靠性修复

收录于 ADWS 1.30 Released / Included in ADWS 1.30 Released.

- 源码安装每次检查并构建三个原生组件，使用 Cargo/Make 增量缓存；不再把“动态库存在”当作版本一致。
- 更名迁移只更新已知命令、组件标识、安装路径及 XDG 路径，保留用户图片名称、网址、描述和历史备份。配置软链接保持不变，通过目标文件完成迁移。
- 安装先停止运行中的桌面与底栏，保存原配置、命令入口、组件库、插件和状态。后续取消、命令失败或新组件启动失败时恢复文件，并重新启动原组件。系统包管理器已经安装的软件包不在回滚范围内。
- 安装备份存放于 `$XDG_STATE_HOME/adws-install-backups/`，默认 `~/.local/state/adws-install-backups/`。每份备份的 `manifest.json` 记录原路径；成功安装有 `complete` 标记。异常退出导致恢复不完整时保留备份供恢复，不能把文件备份等同于断电自动恢复。
- 安装、在线更新、卸载、全局配置导入与首次设置保存共用互斥锁，避免并发替换或删除。
- 复查修复了安装子进程失去控制终端的问题，管理员密码与普通交互输入仍可正常使用；命令结束或失败后归还终端。失败构建即使主进程已退出，也会结束同组残留助手进程后再回滚。
- 组件未能停止时不重复启动；回滚前若新组件仍无法停止，保留现场和备份并报告恢复未完成，避免运行中的组件继续写入已恢复的数据。旧 Python 版本在停止组件前即明确拒绝。
- 任务栏 JSON 与 CSS 先完整写入临时文件、刷新到磁盘，再逐个替换。任一步替换失败时恢复已替换文件，并保留权限与软链接。两个不同路径无法通过普通文件替换实现单次原子提交，但不会暴露截断的文件。
- 更新记录模板基线哈希。未修改模板使用新版；已知用户修改保留；新增用户文件保留。没有基线的旧安装，其冲突模板保存在完整更新备份中，不自动覆盖新版。ADWS 管理的浮动规则始终使用新版。
- 新版移除的默认模板不会被旧版未修改文件重新引入；用户确实修改过的文件仍会保留。
- 迁移保留旧命令入口的归属信息，供新命令安装识别；自启、浮动规则与卸载统一尊重 `NIRI_CONFIG`。
- 在线更新逐个确认组件已经停止；只重启实际停止的组件。新组件无法退出时暂不替换回旧文件，文件恢复失败时不启动组件，并显示备份位置，避免新旧版本混用。更早失败时不重写未修改的动态库和安装记录。
- 在线更新保留安装记录软链接及权限；失败时恢复原动态库软链接。安装记录先校验再下载，缺少状态目录时自动创建。安装记录保存和卸载自启配置也改用完整文件替换，避免截断。
- 全局配置导入先完成备份和临时文件写入，中断或替换失败时恢复已修改的文件，保留配置链接及备份权限；不同配置项指向同一目标时明确拒绝。文件/安装目录已完成移动、状态尚未记录时的中断也纳入恢复检查。
- 首次设置保存前在 `$XDG_STATE_HOME/adws/setup-backups/` 创建文件备份，保留链接、权限与原先不存在的文件状态。默认应用或壁纸应用失败时恢复相关配置文件；恢复失败时报告备份位置，界面恢复操作。任务栏刷新失败会明确告知设置已经保存，自动启动向导取得单实例锁后再次确认是否仍需设置。
- 更名迁移先校验新旧安装记录，损坏时在移动配置前退出并给出简洁提示。同一秒内重复备份使用不同名称，避免覆盖已有备份；替换随附的歌词插件包前保留旧包，相同内容不重复写入。
- 插件关闭全部输出管道却不退出时，运行器在超时后回收进程，不再无限等待。旧版歌词插件保持管道打开、暂停时不重复输出的行为仍然支持。超出数值控件范围的整数在插件设置和输出中作为校验错误处理，避免异常穿透宿主。
- 配色监听遇到回调异常时保留定时刷新并重试，同一错误不重复刷日志；原本可读的样式文件暂时消失时保留上一套颜色，恢复后继续跟随。如果有意停用某份配色，应从上级样式表移除对应引用，而不是仅删除被引用的文件。

Validation: 210 Python tests passed, including isolated fresh-home installs, source builds with fake compilers, partial config-write failure, symlink migration, installation cancellation, failed restart rollback, and shared operation locking. Follow-up regression checks cover a real pseudo-terminal (foreground input and terminal restoration after success/failure), a remaining helper that ignores SIGTERM, removed templates, stop failures, and rejection of old Python before stopping components. Checks also cover partial component stops, incomplete update recovery, inventory/library links and permissions, uninstall/import conflicts, interrupted config imports, aliased targets, invalid inventory data, missing state directories, and interruption immediately after file or installation-directory replacement. Wizard checks cover save/recovery failures, duplicate automatic wizard suppression, migration backup collisions, invalid migration records and plugin-package backups. The latest round verifies bounded cleanup of legacy plugins with closed pipes, oversized numeric settings/output, theme callback retries and retention of the previous palette when files disappear. An isolated Xvfb theme check passed for both a missing imported palette and a missing root stylesheet, followed by successful recovery; existing menu updates and invalid-write recovery still pass. Three earlier isolated Xvfb GUI scenarios passed: normal wizard completion, taskbar refresh failure, and a save/recovery error returning the interface to an interactive state. A separate temporary-home GIO probe confirmed the default-app write location on this host, and the migration CLI reported invalid records without moving configuration. Installer fixtures replace live process discovery and use their own Niri configuration and shell profile paths. Python compilation, translation coverage and installer shell syntax checks passed. These tests do not constitute a fresh-machine full desktop-session lifecycle test. The previously observed idle taskbar stall has not been attributed to these fixes.

Source installs now refresh all native components rather than trusting existing files. Migration rewrites only known identifiers and paths. Installation snapshots and restores owned integration files on failure, and the updater shares its lock. Config saves stage complete files and roll back partial replacements. Template hashes distinguish shipped defaults from user edits; unknown legacy conflicts remain in the full update backup.
