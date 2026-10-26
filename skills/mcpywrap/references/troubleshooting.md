# 按现象定位，不重跑整条流程

先保存目标 project/endpoint/session/group、退出码、error/code/hint 和日志位置，再选下表。查询状态不触发构建或预处理；unknown 不代表没执行。

## 准备、部署与生命周期

| 错误或现象 | 下一步 |
|---|---|
| 缺少命令/选项/能力 | 核对实际 CLI 和目标 worker/运行包；见[安装](setup.md)，不靠更新 Skill 猜支持 |
| init 拒绝已有配置 | 使用原项目，需要恢复依赖时 sync；不删配置 |
| 有效计划 ok=true，但 ready=false / complete=false | 查询成功不代表可构建；按 diagnostics 修复。旧 script list --json 不含依赖任务，见[消费者准备](consumer-prepare.md) |
| prepare_environment_unavailable / prepare_python_unavailable | 核对计划中的解释器及来源要求；sync 可创建缺失环境，但不重建已有环境或下载 Python，见[消费者准备](consumer-prepare.md) |
| consumer_config_invalid / 依赖任务未执行 | 查看配置 issues 和 enabled/disabled/not_transitive 状态；按[消费者准备](consumer-prepare.md)处理，不自动补旧 hooks 或停用失败任务 |
| source_matches=true，但修改表格没生效 | 只比较当前包文件；接管会话没执行预处理，见[项目脚本](project-scripts.md) |
| already_running | 已接管，不是重启/重新部署；按[生命周期](local-development.md)选择更新方式 |
| busy / deployment_in_use / world_in_use | 同项目 status --list 查真实读者/世界占用；只停止自己拥有或用户指定的目标，不清锁 |
| managed_output | build/dev 指向运行目录；改用独立构建目录，游戏更新走 runtime 或重新 run |
| restart_required | 依赖、身份、布局等变化不能当前热更；停止相关读者后重开原世界，不靠 --new 绕过 |
| source_changed | 装配期间输入变了；停止持续写入，稳定后重新发起，不无限重试 |
| deployment_modified | 运行产物被外部改写；保留现场，核对改动和所属会话，不清空全局包 |
| pack_conflict / ownership_changed / link_modified | 支持 deployment 命令的 CLI 先运行 `deployment inspect --json`；跨项目用 `deployment migrate --from <旧目录> --session <失败会话> --json` 预览，组用 --group；确认具体变更后才执行返回的 apply_argv。未知内容不手工删除 |
| plan_stale / deployment_relocated | 前者重新预览现场；后者使用提示的新项目入口，不改 UUID 抢回旧部署 |
| occupancy_unknown | 无法核验进程与部署的关系；保留现场，不自动杀游戏或清锁 |
| recovery_required | 进程身份/退出或事务恢复无法确认；保留恢复路径与日志，先查 status/worker/engine，不删记录或按进程名杀进程 |
| instance_not_ready | 失败创建不是默认可用世界；按提示显式重试该实例，或用户确需新世界时 --new |
| 游戏启动超时/响应丢失 | status --list 找回；观察者超时不获得取消别人启动的权限 |
| PID 身份不匹配 | 不操作这个 PID；确认旧会话是否已结束，不能把复用 PID 当原游戏 |
| 已退出但担心保存 | Windows 进程退出不保证世界保存；重要世界应先在游戏内正常保存 |

## 双客户端与项目脚本

| 错误或现象 | 下一步 |
|---|---|
| joining | Windows 自动加入中；等待 status --group 校验，不并行操作客机菜单或执行客机 Python |
| local_join_failed / local_join_timeout | 保留客机 local-join.json、local-join-menu.json 和日志；确认窗口仍渲染、OCR 语言及目标主机。修复后重启客机；需要手动方式时先停止客机，再 run --clients 2 --join-mode manual |
| lan_target_ambiguous / lan_adapter_unavailable | 端口或注入点无法唯一确认；保留现场，不猜 room_info.port 或套用另一版本地址 |
| waiting_for_join | 客机等待用户点击指定局域网卡片；不要重开第二个独立世界 |
| group_not_ready / 玩家未确认 | status --group 查成员与加入目标；有界等待，保留仍成功的主机 |
| group_required | 用 group 更新；单 session 不能绕过组协调 |
| resource_sync_unverified | 当前组资源热更不支持；重开整组并重新加入，不只更新主机 |
| partial / 某成员失败 | 逐成员/端侧核验；仅重试合适的失败成员，不宣称整组回滚或整组成功 |
| script_failed / script_timeout / script_cancelled | 查 script、script_exit_code、script_log；本次后续流程未继续，但源码可能已改 |
| script_config_invalid / script_not_found | 核对主项目任务表、命令路径与工具解释器，不向游戏环境 pip install |
| script_config_changed | 配置、锁、包身份、世界配置或准备工具源码在操作期间变化；按具体错误稳定输入，再显式重发 |
| script_recursion | 不在脚本里递归调用 mcpy 写操作；组合逻辑放进脚本语言 |
| script_recovery_required | 按 script_state 核对本次脚本进程与后代；未确认退出不删 active/锁记录 |

用法分别见[双客户端](dual-clients.md)和[项目脚本](project-scripts.md)。外部生成器或已开启 watcher 可能消费脚本写到源码的半成品；暂停监控再处理，不能期待自动源码回滚。

## 依赖与环境

- 仅开发环境 / 游戏 import 失败：检查实际组装内容、入口和游戏解释器；不是反复 pip 安装的理由。Git/QuMod、跨平台锁与源码缓存问题见[依赖页](project-dependencies.md)。
- 已执行 mcpy add 但消费者准备仍缺库：它与项目 .venv 是不同环境，按[消费者准备](consumer-prepare.md)中的实际解释器修复，不重复安装到 mcpy 环境。
- 游戏包原生二进制：把工具依赖移出包，使用适配游戏的实现，不绕过校验。
- uv Python 链接失效：bootstrap.py 用 --python <本机解释器>，PowerShell 用 -Python <路径>。
- 找不到引擎/皮肤：本机 doctor；远端在 Windows 服务端准备资源和路径。macOS 原生资源错误见[平台页](macos-local.md)。

## 网络与登录

- unauthorized：检查 HTTP 服务两端 MCPY_REMOTE_TOKEN；不是 MCS 登录问题。
- remote_unavailable / protocol_mismatch / capability_missing：检查 endpoint 和相应端版本，不回退本机。路径与启动规则见[远程执行端](remote-testing.md)。
- component_unavailable：确认当前构建包含 Windows 原生登录组件；只有明确源码开发任务才去仓库开发文档构建，普通 Skill 用户不需要源码。
- studio_unavailable：由用户登录 MC Studio；多个实例需明确目标。component_blocked 按策略错误报告，不自动装证书/关闭保护。
- identity_provided、authenticated、connection_verified 属于不同验证阶段；按[网络会话](network-sessions.md)核对，不把任一字段当作全部业务成功。

## 输入与截图

新输入的 unknown/busy/释放失败，按[统一输入](runtime-input.md#目标界面与清理)查原 operation_id，修复后 input stop 重试释放，不重发计划。后台截图失败按[画面采集](capture.md#截图)报告限制，不自动抢前台或替换后端。

macOS 截图 capability_missing 检查实例运行包，而非授予屏幕录制权限；capture_timeout 表示未及时取得有效渲染帧。录屏和视频提帧在 macOS 本地始终不支持。

只有继续旧脚本时读[兼容输入](input-writing.md)或[旧编排失败处理](input-sequence.md#读结果与处理失败)。原始设备操作确实允许前台时，才处理焦点、窗口尺寸/遮挡；不能让调用端桌面工具恢复不可见的远端窗口。

## 录制与提帧

- capability_missing：检查执行端 media/原生组件，不通过安装 FFmpeg 修复 Windows 系统录制能力。
- busy：同会话已有录像或产物处理中，先查原任务；录制不占输入操作锁。
- recording_timeout：用错误返回 ID 或 record status --session <sid> --list 找回，不立刻再录。
- truncated：核对 end_reason；短片封装完成不证明业务完成。
- invalid_response：校验失败未发布目标，检查两端后重试到新目标；expired/deleted 则源产物已清理。

完整操作与保留期见[画面采集](capture.md)。

## Windows 编码

JSON 的 ASCII 转义由 json.loads/ConvertFrom-Json 还原，不对原始 JSON 查中文标记。脚本读写明确 UTF-8，接受 BOM；bootstrap.ps1 保留 UTF-8 BOM 和管道编码。PowerShell 5.1 的 > / Out-File 默认可能生成 UTF-16，写 JSON 明确 -Encoding utf8。SDK/引擎日志兼容 UTF-8、GBK/GB18030 输入，CLI 保存为 UTF-8。
