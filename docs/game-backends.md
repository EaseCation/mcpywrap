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

Windows 的 `stop/restart` 使用进程终止，不等同于游戏内“保存并退出”，刚写入的数据可能丢失。需要保留进度时，先在游戏中保存并退出到主菜单，再停止进程并 `run` 原实例。`SaveExtraData()` 返回成功或进程显示 `exited` 都不能代替重开读回的保存验证。

macOS 首次 mcpy run 自动从内置发布源安装原生运行包和官方 APK，进度在 stderr；也可提前执行 mcpy engine install。--catalog / --apk 是高级覆盖选项。交互式 run 显示共用调试小窗，ui 打开完整管理页；--no-gui / --detach / --json / --non-interactive 抑制调试小窗；Windows 保持手动安装 MC Studio。默认资源目录 ~/Library/Application Support/mcpy，可设置 MCPY_ENGINE_HOME、MCPY_RUNTIME_CATALOG。

macOS 支持离线 Addon 世界；无认证服务器连接需 CLI 0.4.3+ 与运行包 0.4.3+ 配套，运行包须声明 network_connect_protocol=1（旧 0.4.0 运行包需要显式升级）。connect 与配置了 server 的 run 共用 cppconfig、会话、日志及退出；网络会话仅支持客户端调试，不装配本地 Mod。游戏截图通过支持 screenshot_protocol=1 的 Launcher 按需读帧；macOS 不支持 Map、MCS 登录、原始桌面键鼠或录像，相关能力边界见[内置 Skill](../skills/mcpywrap/references/macos-local.md)。最低 macOS 13.0；具体能力由所选运行包和当前实例诊断确定。运行包采用 ad-hoc 签名，未提供公证。

图形界面的会话操作集中在 ui/session_controller.py；主界面和小窗仅使用共用 SessionControls/PythonConsole 与 LogView。小窗不再另起 Studio TCP 接收器，详见 [共用日志界面](shared-log-ui.md)。

## AI 与纯命令控制

### Windows 多客户端资料路径

Windows 联调成员的生命周期记录、角色归属及占用锁仍位于项目 `.runtime/groups`；游戏实际使用的独立 profile 位于项目所在磁盘的 `mcpy-profiles/<摘要>`。摘要包含项目角色路径及宿主用户目录，不复用用户真实游戏资料；会话的 `network.windows_profile` 与角色目录中的 `windows-profile.json` 记录实际位置。普通单客户端、macOS 不改变布局。

这是 ModPC 3.9 下载包加载器的路径兼容处理：标准 `.../AppData/Roaming/MinecraftPE_Netease/packcache/<包>/` 有固定层数，较深的项目目录会被拼进 Python 模块名。目录链接会被引擎解析为实际路径，不能修复问题；仅覆盖 APPDATA 也不能替代 Windows 按 USERPROFILE 查询目录。使用真实浅层 profile，不修改引擎、sys.path 或 Addon 入口。

首次迁移在角色占用锁内复制旧 AppData 到临时目录，完成归属标记后原子改名，原副本保留。后续启动复用新位置；目标缺失、归属不符或遗留未完成迁移时停止，不回退到旧身份。旧资料的长路径用宿主扩展路径形式复制，传给游戏的仍是标准短路径。需要项目所在磁盘根目录允许创建 `mcpy-profiles`；不支持 UNC 或被替换为目录链接的位置，不自动提权。用户搬迁项目时需保留组记录及其指向的 profile，不能只把外部目录当缓存删除。


Windows/macOS 共同基线是 `--local --project <目录> --non-interactive run --no-gui --detach --json`，后续统一 status/logs/runtime py/runtime reload/stop。控制端不打开 Qt、小窗或 TUI，游戏本身仍需要显示服务及原生窗口。完整操作顺序维护在 [技能的公共流程](../skills/mcpywrap/references/local-development.md)。

`runtime capabilities --session <id> --json` 返回 schema_version=1：control 描述控制端要求，python 提供执行端侧与 worker 队列声明，reload 按同一后端限制返回 available/unsupported/unavailable。查询不执行游戏代码、不返回控制凭据，available 只说明允许调用。旧 worker 缺少队列声明时返回 null，不能推断支持。Windows 已知 Shader 限制也由 WindowsBackend 提供，实际重载与查询没有两份规则。

基线使用同步 Python；可选队列仍以当前会话能力为准。远程调用遇到不支持的队列/等待条件会在发送代码前拒绝，py-result 和本地会话能力查询不会落到本机会话。没有新增服务端协议。

可选 UI/玩家与服务端配套测试见 [手动测试入口](../tests/manual/runtime_controls/README.md)。

两端单人实例共用 cppconfig 的 world_info；存储、启动转换、保存优先级和创建参数见[实例世界设置](instance-world-settings.md)。

版本发现使用 `mcpy --local engine check-updates --json`：实时查询网易 pe/pe_old，返回真实完整版本和 URL；不得递增版本号或猜测 CDN 路径。该命令只检查，不下载或替换实例。新版本 compatibility=not_checked 需实际 APK 校验与结构兼容检查，不能把“发现版本”当作“可运行”。无需先执行此命令：首次 run 的自动安装已经查询 pe。已有本地版本/实例继续运行；缺失的旧版本若不在官方频道中则不可下载，不猜 CDN 路径。

## macOS 游戏图标

安装 APK 时读取 `AndroidManifest.xml` 中 `application/android:icon` 的资源引用，再通过 `resources.arsc` 解析别名和多分辨率变体，选择最大的可解码位图。图标仅来自用户本机已校验的官方 APK，不随 Python wheel 或原生发行包分发。支持 PNG/WebP/JPEG 位图；自适应 XML 存在同资源位图变体时使用该变体，仅有 XML/矢量图时提示暂不支持，不猜用通知或登录图标。

转换结果在每个引擎的 `game` 同级 `icons` 目录保存为透明 PNG 与多尺寸 ICNS（16–1024 像素及 Retina 表示），记录 APK 摘要、资源路径、原始尺寸与输出摘要。保留宽高比和透明度；放大不会增加原始图像细节。已有安装在下一次启动时可从匹配的 APK 缓存自动补全，不需要重装游戏。缓存已删除时可执行 `mcpy engine install --apk <匹配的原 APK>`；缺少图标不会阻止游戏启动。

游戏启动前，在安装锁内按原生运行包和图标摘要创建 `runtimes/<id>/applications/<摘要>/Minecraft China.app` 本地副本，设置中文应用名、`CFBundleIconFile`，重新进行 ad-hoc 签名并验证。之后复用副本，每次启动检查签名。原始运行包的文件、发行完整性清单和签名不变；本地副本只用于实际游戏进程，实例固定的原生运行版本、游戏资源、数据目录和控制协议仍保持原绑定。图标转换或签名失败时向 stderr 记录原因，继续使用原始运行包。无需 Xcode、Android SDK、Pillow 或重新编译原生启动器。
