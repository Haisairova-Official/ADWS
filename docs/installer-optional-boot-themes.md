# 可选登录与启动主题

登录主题和启动主题是独立的可选模块。安装器默认选择 `preserve`，保留现有主题、登录管理器及引导链，不申请管理员权限，也不安装、切换或重启这些组件。

本模块不把“软件包已安装”当作“正在使用”。它复用登录管理器检测，通过活动服务、`display-manager.service` 的指向或发行版的默认管理器文件识别 SDDM、Plasma Login Manager、GDM 和 LightDM。磁盘上存在 GRUB 或 systemd-boot 文件只记作候选；当前引导器优先以 `bootctl status` 的 `Current Boot Loader` 为证，无法确定时显示未知。

## 支持范围

| 项目 | 可自动执行的情况 | 其他情况 |
| --- | --- | --- |
| 登录主题 | 当前选用 SDDM，并且所选主题已经完整安装 | Plasma Login Manager、GDM、LightDM 及未知管理器保留现状，报告不支持自动切换 |
| 启动主题 | Plymouth、主题及模块已安装；已启用 Plymouth hook 和 `splash` 参数；只有传统 mkinitcpio 生成链，preset 为可解析的静态配置，现有内核和 initramfs 完整 | initramfs-tools、dracut、多生成器、自定义动态 preset、未知输出或 hook 设置不自动执行 |
| UKI、静态启动图 | 只读识别 EFI 文件的 `.linux`、`.splash` 段，检查 ukify、kernel-install 和 preset 中的 UKI／签名配置 | 检测到 UKI、签名或静态启动图链时阻止传统 initramfs 主题操作，保留现有方案 |
| GRUB / systemd-boot | 只读检测 | 不修改默认启动项、引导器、GRUB 配置或 EFI 安装状态 |

这里只支持选择**已安装**的主题。安装主题包、修改启动参数、添加 Plymouth hook 或配置签名链需要另行展示和批准变更，不能混入选择主题这一步。首次支持范围保持保守，不能因此把其他发行版写成“完整支持”。

## 审核及配置优先级

`plan(login_theme="preserve", boot_theme="preserve")` 返回检测结果、文件变更、输入文件哈希、待备份的引导镜像、固定命令、冲突和生效时机。计划生成不写入系统。

SDDM 使用 `/etc/sddm.conf.d/99-adws-theme.conf` 保存 `[Theme] Current`。如果 `/etc/sddm.conf` 或排序更后的配置覆盖该项，先列出冲突。若目标片段已被用户占用，也不会覆盖。不会自动改动默认登录管理器、已有桌面会话或自启动服务。

Plymouth 只合并 `/etc/plymouth/plymouthd.conf` 的 `[Daemon] Theme`，保留其他选项和注释。重建命令仅为审核过的每个 preset：

```text
/usr/bin/mkinitcpio --nopost --preset /etc/mkinitcpio.d/<已检测的文件>.preset
```

`--nopost` 阻止本次重建顺带运行引导器、签名等事后 hook；现有 mkinitcpio 的构建 hook 仍属于系统生成链。preset 仅允许静态字面值，拒绝 shell 操作符、命令替换、未知变量及能够改变输出路径的自定义选项。执行环境使用固定系统路径，不继承用户的 shell 启动变量。

## 应用、备份和回滚

调用接口：

```python
report = detect(root=Path("/"))
proposal = plan(login_theme="已安装的主题名", boot_theme="preserve")
result = apply(proposal, Path("/var/lib/adws/boot-theme-backups/<唯一标识>"))
recovery = rollback(result["backup"])
```

主安装流程仅在明确选择了主题并完成审核后，以管理员权限调用 `--apply-plan <计划文件>`。`--rollback <备份目录>` 为专用恢复入口。两者最后一行均输出 JSON，便于安装器保存状态；`--inspect` 仅检测。普通用户配置快照不能替代这个系统文件事务。

应用前会重新检测、重新生成命令并比对配置、主题源和内核输入的哈希。修改前完整备份配置和每个将重建的 initramfs，并校验备份。检测到其他 ADWS 主题事务或 Arch 包事务时停止，不争抢系统状态。

备份保存在 `/var/lib/adws/boot-theme-backups/<唯一标识>/`，包含完整 `journal.json` 和原文件。执行失败会尝试恢复本次配置和镜像。外层安装失败可以再次调用专用回滚；如果用户或包管理器后来修改了文件，回滚报告冲突并保留后续修改，不强制覆盖。

断电或进程被强制终止可能留下尚未记录完成哈希的镜像。此时仍保有原镜像备份，但自动回滚不能判断当前镜像的来源，会报告需要人工恢复，不能冒充已完成恢复。不会自动删除旧备份。

成功结果是 `applied-pending-session-validation`：登录主题等待下一次登录确认，启动主题等待重启确认。这个状态不是安装失败，也不是已经完成实机视觉验收；主流程应记录待确认项，不因待确认自动回滚。

## 验证范围

回归测试使用临时根目录和模拟的重建命令，覆盖默认保留、管理器识别、配置优先级、UKI 与静态启动图、动态 preset 拒绝、输入变化、完整镜像备份、失败回滚、后续修改保护及备份路径冲突。测试不会运行本机重建、修改登录管理器或重启会话。干净 Arch 上登录、重启及恢复的实际验收仍应单独记录。

## 官方资料

- [SDDM 配置及优先级](https://man.archlinux.org/man/sddm.conf.5.en)
- [Plymouth 主题切换与 initrd 重建](https://man.archlinux.org/man/plymouth-set-default-theme.1.en)
- [mkinitcpio preset、UKI 与 `--nopost`](https://man.archlinux.org/man/mkinitcpio.8.en)
- [bootctl 状态检测](https://www.freedesktop.org/software/systemd/man/latest/bootctl.html)
- [ukify 的签名与 Splash 配置](https://www.freedesktop.org/software/systemd/man/latest/ukify.html)
- [systemd-stub 的 UKI 与 `.splash` 段](https://www.freedesktop.org/software/systemd/man/latest/systemd-stub.html)
