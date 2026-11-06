# Shorin Arch Setup 安装流程参考

核对日期：2026-11-06。参考版本：[`e442234bd56cea67d18e2190563b2fda04b35e1c`](https://github.com/SHORiN-KiWATA/shorin-arch-setup/tree/e442234bd56cea67d18e2190563b2fda04b35e1c)。本文只读分析该仓库公开文件；没有运行其安装、回滚或下载脚本，也没有复制其实现。ADWS 的最高要求仍是 [安装与交付纲领](installer-roadmap.md)。

这套工程最值得参考的是交付组织：先选方案，将组件、应用与配置组合起来，分阶段执行，最后核对缺失内容，并提供独立恢复入口。ADWS 应沿用这条产品流程，并补上保留用户环境、按能力生成配置和真实功能验收。

## 可以吸收的设计

| 来源 | 已观察到的设计 | ADWS 应采用的方式 |
| --- | --- | --- |
| [install.sh](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/install.sh) | 开始选择桌面与可选模块，显示系统信息；模块按阶段执行，执行失败停止，记录进度与日志。 | 入口集中收集 fresh / integrate / migrate、功能、默认应用、下载方式和镜像选择；展示完整变更清单后执行。每一步显示正在做什么、成功或失败原因。 |
| [scripts/04j-minimal-niri.sh](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/04j-minimal-niri.sh) | Niri、终端、文件管理、剪贴板、锁屏、输入主题等成套交付；为普通目标用户创建空显示配置，避免默认带入作者屏幕。 | 功能清单同时描述包、配置、服务和验收；默认快捷键只能引用实际安装的程序。显示器参数在目标机检测，旧机配置不能覆盖目标屏幕与显卡。 |
| [common-applist.txt](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/common-applist.txt) 与 [scripts/99-apps.sh](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/99-apps.sh) | 应用清单独立维护，带用途说明；可多选、区分来源，失败应用有汇总。 | 必需功能依赖和可选软件分开；让用户先选终端、浏览器、文件管理器和编辑器，安装后核对 `.desktop` 及命令，再同步快捷键、默认应用与文件关联。 |
| [minimal-niri 的配置](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/minimal-niri-dotfiles/.config/niri/config.kdl) 与 [快捷键](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/minimal-niri-dotfiles/.config/niri/binds.kdl) | 快捷键、规则、布局、显示配置分开；包含应用启动、截图、声音、亮度、剪贴板及锁屏；明确说明输入法不能重复自启。 | 新配置提供完整常用操作；逐项由目标 Niri 的 `validate` 验证。已有配置只增补受管部分。Niri、XDG、自启动服务共同查重，不通过杀进程掩盖冲突。 |
| [scripts/05-verify-desktop.sh](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/05-verify-desktop.sh) | 安装阶段写出包清单，结尾用包管理器核对，并检查部分配置路径和软链接；发现缺失退出。 | 保留安装后对账；进一步检查命令、导入模块、动态库、资源文件，再进入图形会话验证预览、截图、剪贴板、真实应用启动和任务栏。 |
| [scripts/00-utils.sh](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/00-utils.sh) | 统一日志、命令执行结果、用户选择及登录管理器冲突检查。 | 统一执行与报告接口，识别实际目标用户、现有显示管理器、启用服务和登录入口；保留 SDDM、Plasma Login、GDM 等已有选择。 |
| [初始快照](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/00-btrfs-init.sh)、[桌面安装前检查点](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/03c-snapshot-before-desktop.sh) 与 [undochange.sh](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/undochange.sh) | 基础安装前和桌面安装前分别建立恢复点，提供独立回滚入口。 | 配置事务必须有可查的备份清单和单独恢复入口；已有 Btrfs/Snapper 可以作为显式可选的额外保护，不作为所有文件系统的前提。 |

## 必须与 ADWS 要求区分的地方

1. **安装范围不同。** 该工程面向 Arch 整机环境配置；基础阶段会配置软件源、语言、字体等，必要软件阶段会部署整套音频与输入法方案。ADWS 默认只安装选中的功能依赖，保留已有输入法和音频后端，不更换驱动、删除原输入法或默认修改引导。参考：[基础设置](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/01a-base.sh)、[必要软件](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/02b-musthave.sh)。

2. **续装不能只看完成标记。** `install.sh` 将模块名写入安装目录下的 `.install_progress`，再次运行时跳过这些模块；成功结束删除该文件。ADWS 要把计划和进度放到持久状态目录，绑定源版本、计划及目标用户，续装先核对真实安装结果；用户修改过的配置必须报告冲突，不能仅凭旧标记跳过。

3. **安装前集中确认不能被中途默认选择替代。** 该工程还有镜像、登录管理器和常用软件等后续询问；部分询问超时后采用默认值，常用应用选择超时会安装整份清单。ADWS 应在开始阶段确定选择；非交互运行缺少必要决定时停止，不能把等待超时当作授权。参考：[入口](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/install.sh)、[常用软件](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/99-apps.sh)。

4. **整目录复制不等于配置迁移。** minimal-niri 调用公共 `force_copy` 部署用户文件，该函数使用递归覆盖；默认 Niri 配置和 MIME 文件也带固定程序、语言及渲染器选择。ADWS 要逐文件记录原状、处理冲突；保留语言、主题及个人修改。默认程序缺失时先安装或重新选择，不能留下空快捷键。参考：[公共工具](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/00-utils.sh)、[默认关联](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/minimal-niri-dotfiles/.config/mimeapps.list)。

5. **包齐全不代表功能验收通过。** 参考验证器主要核对包与少量配置目录，minimal-niri 没有专属配置检查分支；它并未在该文件中验证真实捕获、剪贴板往返或任务栏交互。ADWS 的依赖探测、容器检查、嵌套图形测试、实机验收必须分别报告，不能合并为绿色“完成”。可选软件安装失败报告也必须保留失败状态。参考：[验证器](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/05-verify-desktop.sh)、[常用软件结果](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/99-apps.sh)。

6. **恢复范围需要明确。** `undochange.sh` 依据检查点恢复 Btrfs 根卷和可用的 home 子卷，最后重启。这是整机恢复，可能包含安装后用户产生的改动；ADWS 默认回滚本次事务接管的配置，已安装软件包单列。卸载删除 ADWS 项时继续保留用户修改后的系统设置，整机恢复只能另行明确选择。

7. **镜像和权限不能照搬。** 参考入口会按时区调整镜像流程，部分路径查询 IP 地区；若无国内仓库，基础阶段会添加仓库。ADWS 先检查现有代理和镜像配置，仅中文环境提供国内镜像选择，不自动查询 IP。安装主流程使用普通用户，只为具体包管理操作提权，不设置临时无限制免密 sudo。参考：[入口](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/install.sh)、[基础设置](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/01a-base.sh)、[minimal-niri 安装](https://github.com/SHORiN-KiWATA/shorin-arch-setup/blob/e442234bd56cea67d18e2190563b2fda04b35e1c/scripts/04j-minimal-niri.sh)。

## 对当前 ADWS 实施的结论

- 保留“选方案 → 展示变更 → 分阶段执行 → 核对交付 → 给出恢复入口”的组织方式，以 ADWS 独立实现落地。
- 先补完整功能清单、配套默认配置、统一启动与默认应用，再完善迁移、功能验收及引导器。无需为了参考项目的广度扩展其他桌面适配。
- 常用软件菜单可作为后续可选模块；不能为了菜单完整而把浏览器、游戏或开发工具整包强装到用户系统。
- 当前默认配置的亮度热键继续使用 ADWS 已有合并提交队列，避免恢复直接高频 DDC 查询；默认背景使用 Niri 自身支持的中性色，保留现有壁纸，不额外启动竞争的壁纸进程。
- 本文是设计审阅记录，不是执行该参考安装器的报告，也不代表 ADWS 的 [发布验收矩阵](platform-support.md) 已经完成。
