# Fcitx5 崩溃检查，2026-10-08

- 当前启动前无 Fcitx5 进程。
- 今日转储：11:31:21 PID98359、11:39:08 PID137079；均 SIGABRT。
- 版本：fcitx5-shorin-patched-git 5.1.22.r5.g4146a2a7-1，libime1.1.17、chinese-addons5.1.15。
- 最新转储：libFcitx5Utils.so.2 +0x1e3e1，objectvtable_sdbus.cpp异常捕获路径。
- 核心内异常对象 what()：failed to insert zero-length key。
- 活动 D-Bus 方法元数据：org.fcitx.Fcitx.InputContext1 / ProcessKeyEvent。
- 这证明崩溃发生于处理按键期间的空键异常；尚不能证明是补丁、云拼音、用户词库或 ADWS 导致。
- user.dict 与4个附加.dict均能由libime_pinyindict解码；未删除、改写或移动词库。
- 云拼音目前启用。尚未进行关闭云拼音或替换官方包的对照实验。
- 尝试按原配置启动时，D-Bus 名称已被另一 Fcitx5 进程持有。随后确认 PID146960 已运行；未强制替换或结束该进程。

下一步：若再次复现，可先备份后临时关闭云拼音对照；若仍复现，比较官方Fcitx包或获取带调试符号的原构建。更换系统包需另行决定。

## 后续追查

- 相同异常字符串只出现在本机 libIMECore.so；对应 DATrie 对空键的防护。
- 使用本机 LibIME1.1.17，独立执行 HistoryBigram.add(vector<string>{""}) 能稳定抛出相同异常，不依赖Fcitx、皮肤或ADWS。
- user.history 能正常加载；加载后独立加入空词仍产生同一错误。测试不保存学习历史。
- LibIME1.1.17及当前master的HistoryBigramPool.add仅检查词条中是否含NUL，未排除空词条，随后无条件更新unigram trie。
- 已安装chinese-addons5.1.15普通候选提交(updateUI)调用context.learn，不捕获此异常；cloudPinyinSelected内学习部分有异常捕获。因此普通候选提交/学习链比“云拼音请求本身抛错”更贴合此次崩溃。
- Shorin已安装commit4146a2a7相对官方5.1.22，最终差异只有XIM按键释放转发过滤；当前核心活动方法是D-Bus ProcessKeyEvent，所以补丁直接导致此次崩溃的证据较弱，不能凭包名判定。
- 尚未定位哪个候选或上下文生成了空词；独立API复现证明缺少防护，不等于证明用户输入的完整复现路径。
- 后续最有价值的对照：备份后暂时关闭Learning；若不复现则聚焦学习链，再对照CloudPinyinEnabled和具体按键步骤。此检查没有更改配置或系统库。

官方源码：
- https://github.com/fcitx/libime/blob/1.1.17/src/libime/core/historybigram.cpp
- https://github.com/fcitx/libime/blob/1.1.17/src/libime/core/datrie.cpp
- https://github.com/fcitx/fcitx5-chinese-addons/blob/5.1.15/im/pinyin/pinyin.cpp
- https://github.com/SHORiN-KiWATA/fcitx5/compare/fcitx:5.1.22...4146a2a7

- 用户反馈：没有稳定触发动作，“随时都有可能”。
- 第二份独立转储PID98359（11:31:21）中，同样提取到异常对象内容 failed to insert zero-length key；两次为相同故障。


## 2026-10-09：再次崩溃后的本机缓解

- 用户提供的17:30两次崩溃（PID1430807、1431111）仍为`failed to insert zero-length key`，并非仅凭enchant可选后端缺失警告判定原因。
- 再次使用本机库运行独立复现器：现有user.history加载成功；加入空词抛出同一异常。完整用户输入触发链仍未捕获，不能声称已经修复LibIME本身。
- 备份路径：`/home/akizuki/.local/state/fcitx5-recovery/20261009-173345/`，包含pinyin.conf、user.dict、user.history。
- 通过Fcitx Controller SetConfig仅将Learning由True改为False；GetConfig与磁盘配置均确认生效。云拼音保持开启。此为暂时避开学习路径的应急修复；不再学习新词/选词频率，已有词库与记录保留。
- 操作后校验user.dict和user.history哈希与备份一致，没有删除、重建或清空用户数据。原进程PID1434724持续运行，未重启输入法。
- 独立D-Bus与临时XDG目录中，禁止D-Bus自动启动另一服务，禁用图形前端；连续100次中文候选提交、720次按键处理通过，Learning=False。测试不连接当前应用，也不写入个人词库。
- 测试记录：`/tmp/fcitx-smoke-bbm8tkau/daemon.log`。这是短时基本功能验证，不代表已证明长期随机崩溃彻底消失。
- 如以后修复底层库，需要重新开启Learning并复测；可在拼音设置中恢复学习，也可利用备份恢复原配置。不要恢复旧词库覆盖其后产生的新记录。
