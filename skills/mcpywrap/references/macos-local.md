# Apple Silicon macOS 本地测试

先执行 `mcpy --local doctor --capabilities --json`。必须实际报告 `macos-local-worlds`；不要仅凭存在 run 命令推断支持。功能可用与资源就绪分别看 capabilities、resources_ready。Intel Mac 不支持原生本地后端；Apple Silicon 上的 Rosetta Python 仍可启动 arm64 游戏。

```sh
mcpy --local engine doctor --json
mcpy --local --non-interactive engine install --json  # 可选：提前准备；run 也会自动安装
mcpy --local --project <Addon项目> --non-interactive run --no-gui --detach --json
```

mcpy 内置 EaseCation 的固定 HTTPS 启动器发布源；首次 run 自动通过网易 pe 发现并下载最新开发者 APK，不向用户索要 catalog 或 APK 路径。显式 --catalog、MCPY_RUNTIME_CATALOG 和已保存来源优先于默认值，适合开发者覆盖；--apk 只用于已有匹配 APK 的离线导入。下载和提取进度在 stderr，--json 的 stdout 保持单个结果对象。失败时按实际网络/校验/空间错误处理，不反复猜 URL 或改用未经适配的上游启动器。

默认资源目录为 ~/Library/Application Support/mcpy，MCPY_ENGINE_HOME 可隔离。无需 Homebrew、Wine、已安装的 Launcher 或 MPay 账号。发布目录中的 APK profile 只是构建验收基线。正式目录声明 apk_source=netease-pe；首次安装动态发现完整版本和 URL，从实际 APK 校验开发者身份与 ARM64 核心、计算摘要，再做结构兼容检查。官方首次下载没有预先发布的可信 SHA-256；HTTPS 来源、ETag 分段一致性、ZIP 校验和结构检查通过后记录摘要，后续缓存/运行按该摘要校验。

支持离线 Addon 世界和源码 Python Mod，使用既有项目构建/依赖能力。支持 cppconfig_protocol=1 的新运行包可按实例选择地形、模式、难度、种子及规则，见[实例世界设置](instance-world-settings.md)；旧运行包仍使用原来的平坦创造启动参数。默认重开最新实例，--new 新建；run --list 列出，run <ID前缀> 指定。项目 .runtime/macos/instances 保存世界，每个实例固定运行包与 APK。安装新版不会迁移原世界；发现版本不匹配时说明原因，不自动删除/重建。已有实例的 Mod 修改需先 stop 再 run，运行中再次 run 只返回现有会话。

run 返回进程启动，随后 status 的 world_ready=true 表示已观察到 HUD；还需验证客户端/服务端日志和实际玩法。日志使用 logs --source engine/game/worker。源码构建通过并不证明服务端 Mod 执行。

```sh
mcpy --local --project <项目> runtime py --session <sid> --side client --code "print('client probe')" --json
mcpy --local --project <项目> runtime py --session <sid> --side server --code "print('server probe')" --json
mcpy --local --project <项目> stop --session <sid> --json
```

客户端使用 launcher-jni，启动期间可以 --no-wait 提交并用 runtime py-result 按 request_id 查询；--wait-until 是无副作用的客户端 Python 就绪表达式。超时先查原请求，勿重复提交有副作用代码。服务端仍走原有 Safaia，仅进入世界后可用，不给服务端加客户端队列参数。runtime install/ui/player 继续通过公共客户端通道工作；注入的 mcpy.* 仍严格仅用于临时调试。

暂不支持本地 Map、联机服务器、MCS 身份、MCEditor 及 Windows screenshot/key/mouse/input-sequence/record。需要它们时使用显式 Windows --remote，不静默回退或尝试登录。macOS 前台 run 的 Ctrl+C 请求保存退出；一次性测试结束必须 stop 并确认进程退出，关闭自己创建的窗口。

最低版本为 macOS 13.0，游戏实测仅 26.6.2；包目前 ad-hoc 签名，未公证，不宣称已验证最低系统或 Gatekeeper。失败时提供实际错误及日志，不能建议全局关闭系统保护。


Windows 与 macOS 共用 PySide6 界面：人工使用 `mcpy --local --project <项目> ui`；人工 run 默认只显示游戏和紧凑调试小窗，Agent 使用 --non-interactive run --no-gui --detach --json。界面提供依赖管理、Mod 模板、实例、运行资源引导、Debug 日志、双端 Python、文件热更、自动监控、保存退出和重新部署重载世界。MCEditor 在 macOS 明确禁用。

`runtime watch --session <sid> --side client|server|both` 与 GUI 共用监控服务，停止监控保留游戏。模块热更只对已加载模块执行源码，修改实例方法、事件注册、新增入口或资源应保存重载世界，避免重复注册。both 仅适合可安全重复执行的公共模块。

新运行包声明 addon_link_protocol=1 时，行为包/资源包软链接到实例 assembled 目录，多依赖仍由统一组装器合并；不复制第二份运行包。旧运行包固定在原实例，保留复制兼容流程。Qt 与原生启动器有各自的系统下限：本机 Qt 6.11.2 的 Mach-O 最低 macOS 13.0，正式原生运行包也统一要求 macOS 13.0；最低版本的实际游戏表现仍需单独验证。

人工交互式 mcpy run 或通过 mcpy ui 启动游戏后自动出现可折叠、可置顶的彩色日志小窗，与主界面共享会话、日志和监控。关闭小窗只隐藏视图；结束测试仍使用 stop 或“保存退出”，不能把小窗消失当成游戏已退出。新会话不要另起 studio_server_ui --port 监听器。

当前开发包 3.9.100.297020 的资源热更范围：已有微软粒子 JSON 更新后新建发射器已实测生效，回执仍只为 triggered/effect_verified=false；新增粒子文件未被识别时需重载世界。JSON UI 使用声明 json_ui_reload_protocol=1 的新运行包（local6 起），通过同一个 runtime reload ui 命令更新定义；旧包的 Ctrl+R 仍无效，安装新版后需显式启动新实例。原生重载会使现有自定义控件失效，此 APK 不触发 UiInitFinished；需按 Mod 原有逻辑重新 RegisterUI/CreateUI 和绑定回调，不使用旧控件句柄，也不把调试模块 _mcpy_launcher 写入业务代码。只验证了现有文件中的定义变化；新文件/复杂继承需单独验收。材质和 Metal Shader 仍返回 unsupported，不使用 ForceReloadResourcePack 绕过提示。True/triggered 只是已投递，不证明解析成功或界面已更新；错误 JSON 也可能被接受，需核对实际画面和文字。

日常开发和 AI 操作遵循 [Windows/macOS 公共无交互流程](local-development.md)，不需要编写平台专用脚本。上述安装与引擎限制是后端差异，run/status/logs/runtime/stop 的调用方式相同。

FPS/VSync、画质、GUI 缩放、音量和输入偏好由 mcpy worker 按用户保存并在新会话导入，位置是引擎资源根目录下的 `preferences/macos`。这些不是 cppconfig 世界设置；不要为每个新实例重新配置。运行中的其他实例不会即时跟随，重开时读取最新值；先正常保存退出以确保游戏完成原生配置写入。

版本发现使用 `mcpy --local engine check-updates --json`：实时查询网易 pe/pe_old，返回真实完整版本和 URL；不得递增版本号或猜测 CDN 路径。该命令只检查，不下载或替换实例。新版本 compatibility=not_checked 需实际 APK 校验与结构兼容检查，不能把“发现版本”当作“可运行”。无需先执行此命令：首次 run 的自动安装已经查询 pe。已有本地版本/实例继续运行；缺失的旧版本若不在官方频道中则不可下载，不猜 CDN 路径。
