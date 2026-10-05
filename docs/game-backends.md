# 本地运行后端

CLI、TUI 和 session worker 使用 `engines.backend.GameBackend`，由 `get_backend()` 在一个位置选择 Windows、Apple Silicon macOS 或不支持的平台。远程路由仍先于本地回调执行，远程失败不会自动改为本地启动。会话记录保存后端 ID，恢复/停止已有会话不重新猜测它的平台。

接口边界：

| 操作 | 后端责任 | 公共层责任 |
|---|---|---|
| diagnose / install | 发现和校验资源、安装方式及限制 | doctor/engine 命令、交互确认、进度展示 |
| run / connect | 实例、组装和具体启动配置 | 命令参数和远程路由 |
| launch | 创建具体游戏进程，报告是否需采集 stdout | worker、日志接收、进程身份、状态持久化 |
| debug_channel | 提供统一 execute 等 Python 调用 | 控制服务、runtime 命令 |
| refresh / handoff | 后端就绪判断和附加诊断 | status/会话交接，不按平台分支 |
| capabilities / reload_restriction / ui_reload_code | 声明入口和版本限制、提供 UI 重载代码 | doctor 和 runtime capabilities 查询；CLI/Qt 共用 reload_session、结果处理 |

WindowsBackend 调用原有 MC Studio 发现、cppconfig 和 Safaia 流程，保留现有引擎实现。Qt6 项目界面、日志视图、模板和热更监控由两端共用，详见 [Qt6 开发界面](qt6-development.md)。macOSBackend 用同一 AddonProjectBuilder、sessions 和 RuntimeControlServer，内部负责 APK 资源、打包启动适配器和 LauncherPythonChannel。服务端 Python 仍通过 Safaia；新增原生通道只负责客户端。

调用端通常只需要 run/status/logs/stop/runtime py。启动器位置、游戏库路径和底层 socket 是后端细节；`backend` 字段供诊断，业务代码应按 capability 和公共状态判断。`running` 表示进程启动，macOS 的 `world_ready` 才表示已观察到 HUD；Mod 是否正常还要核对实际游戏日志和玩法效果。

macOS 安装：`mcpy --local engine install --catalog <catalog.json> [--apk <文件>]`。没有默认公开发行源时，交互终端引导选择；非交互返回明确 setup_required/catalog_unconfigured，不挂起等待输入。默认资源目录 `~/Library/Application Support/mcpy`；可设置 MCPY_ENGINE_HOME、MCPY_RUNTIME_CATALOG。源码项目内无参数启动显示终端菜单，初次 run 可触发安装引导。

macOS 当前只支持离线 Addon 世界，不支持 Map、服务器连接、MCS 登录或 Windows 桌面截图/键鼠/录像；需要这些能力时显式使用 Windows 远程端。编译目标 macOS 11.0，实际游戏只在 26.6.2 验证。运行包尚为 ad-hoc 签名、公证待完成。

图形界面的会话操作集中在 ui/session_controller.py；主界面和小窗仅使用共用 SessionControls/PythonConsole 与 LogView。小窗不再另起 Studio TCP 接收器，详见 [共用日志界面](shared-log-ui.md)。

## AI 与纯命令控制

Windows/macOS 共同基线是 `--local --project <目录> --non-interactive run --no-gui --detach --json`，后续统一 status/logs/runtime py/runtime reload/stop。控制端不打开 Qt、小窗或 TUI，游戏本身仍需要显示服务及原生窗口。完整操作顺序维护在 [技能的公共流程](../skills/mcpywrap/references/local-development.md)。

`runtime capabilities --session <id> --json` 返回 schema_version=1：control 描述控制端要求，python 提供执行端侧与 worker 队列声明，reload 按同一后端限制返回 available/unsupported/unavailable。查询不执行游戏代码、不返回控制凭据，available 只说明允许调用。旧 worker 缺少队列声明时返回 null，不能推断支持。Windows 已知 Shader 限制也由 WindowsBackend 提供，实际重载与查询没有两份规则。

基线使用同步 Python；可选队列仍以当前会话能力为准。远程调用遇到不支持的队列/等待条件会在发送代码前拒绝，py-result 和本地会话能力查询不会落到本机会话。没有新增服务端协议。

技能 smoke.py 新增 --client-file/--server-file，使用同一 CLI 等待世界/HUD、分别执行一次验收脚本、收集 JSON/日志并 finally 停止自己创建的游戏。2026-10-05 在 macOS local6 真机验证双端 ModSDK 同一世界返回正常，脚本自动保存关闭。Windows 契约和路由通过自动测试覆盖，本轮没有 Windows 真机复测。
