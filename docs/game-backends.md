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

macOS 首次 mcpy run 自动从内置发布源安装原生运行包和官方 APK，进度在 stderr；也可提前执行 mcpy engine install。--catalog / --apk 是高级覆盖选项。交互式 run 显示共用调试小窗，ui 打开完整管理页；--no-gui / --detach / --json / --non-interactive 抑制调试小窗；Windows 保持手动安装 MC Studio。默认资源目录 ~/Library/Application Support/mcpy，可设置 MCPY_ENGINE_HOME、MCPY_RUNTIME_CATALOG。

macOS 当前只支持离线 Addon 世界，不支持 Map、服务器连接、MCS 登录或 Windows 桌面截图/键鼠/录像；需要这些能力时显式使用 Windows 远程端。编译目标 macOS 11.0，实际游戏只在 26.6.2 验证。运行包尚为 ad-hoc 签名、公证待完成。

图形界面的会话操作集中在 ui/session_controller.py；主界面和小窗仅使用共用 SessionControls/PythonConsole 与 LogView。小窗不再另起 Studio TCP 接收器，详见 [共用日志界面](shared-log-ui.md)。

## AI 与纯命令控制

Windows/macOS 共同基线是 `--local --project <目录> --non-interactive run --no-gui --detach --json`，后续统一 status/logs/runtime py/runtime reload/stop。控制端不打开 Qt、小窗或 TUI，游戏本身仍需要显示服务及原生窗口。完整操作顺序维护在 [技能的公共流程](../skills/mcpywrap/references/local-development.md)。

`runtime capabilities --session <id> --json` 返回 schema_version=1：control 描述控制端要求，python 提供执行端侧与 worker 队列声明，reload 按同一后端限制返回 available/unsupported/unavailable。查询不执行游戏代码、不返回控制凭据，available 只说明允许调用。旧 worker 缺少队列声明时返回 null，不能推断支持。Windows 已知 Shader 限制也由 WindowsBackend 提供，实际重载与查询没有两份规则。

基线使用同步 Python；可选队列仍以当前会话能力为准。远程调用遇到不支持的队列/等待条件会在发送代码前拒绝，py-result 和本地会话能力查询不会落到本机会话。没有新增服务端协议。

smoke.py 的 --client-file/--server-file 通过同一 CLI 等待世界/HUD、分别执行一次脚本、收集 JSON/日志，并停止自己创建的游戏。可选 UI/玩家与服务端配套测试见 [手动测试入口](../tests/manual/runtime_controls/README.md)。

两端单人实例共用 cppconfig 的 world_info；存储、启动转换、保存优先级和创建参数见[实例世界设置](instance-world-settings.md)。
