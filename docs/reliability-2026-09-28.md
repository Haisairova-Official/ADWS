# Reliability follow-up — 2026-09-28 / 可靠性复查

收录于 ADWS 1.30 Released / Included in ADWS 1.30 Released. Continues [the previous review](reliability-2026-09-22.md).

- 修复插件运行器在任务栏关闭输出连接后，继续向同一管道报告错误、引发多层 BrokenPipeError 和退出刷新异常的问题。现在停止输出并回收插件进程；连接仍有效时保留正常的错误记录与错误组件显示。
- 缓存记录即使是合法 JSON，也可能具有错误类型。列表、空值、字符串和数字现在会被视为失效记录，重新解包，而不是因属性访问异常阻止插件启动。
- 插件覆盖安装先复制完整临时包并刷新到磁盘，再替换目标。复制失败保留原包，保持原有软链接；禁止覆盖的安装使用排他发布，避免并发创建导致误覆盖。此修改不等于断电事务保证。

验证：215 项 Python 测试通过，包含 5 项新增回归。真实管道测试覆盖正常输出、错误输出和启动参数校验期间消费者关闭连接，检查无堆栈刷屏、正常退出且插件子进程已回收。另覆盖错误类型缓存记录、安装中途写入失败、软链接保留，以及并发排他安装。Python 编译及翻译覆盖检查通过。

运行状态检查中，当前桌面与底栏进程均在运行。历史任务栏日志混有旧版 MNWS 的断管记录和从任务栏启动的第三方应用输出，不能将全部错误行归为 ADWS 当前故障。本轮没有重启真实桌面，也没有重新验证完整桌面生命周期或把间歇性卡顿归因于上述问题。

The runner now handles a disconnected consumer without cascading broken-pipe errors and still reaps its plugin process. Invalid cache-stamp types trigger reconstruction. Plugin copies are staged before replacement, retain destination symlinks, and prevent concurrent overwrites when replacement is disabled. All 215 Python tests pass; existing live components were not restarted during this review.
