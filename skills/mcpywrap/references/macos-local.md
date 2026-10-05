# Apple Silicon macOS 本地测试

先执行 `mcpy --local doctor --capabilities --json`。必须实际报告 `macos-local-worlds`；不要仅凭存在 run 命令推断支持。功能可用与资源就绪分别看 capabilities、resources_ready。Intel Mac 不支持原生本地后端；Apple Silicon 上的 Rosetta Python 仍可启动 arm64 游戏。

```sh
mcpy --local engine doctor --json
mcpy --local --non-interactive engine install --catalog <发行方的catalog.json路径或HTTPS地址> --apk <本机开发者APK> --json
mcpy --local --project <Addon项目> --non-interactive run --detach --json
```

当前没有默认公开发行地址；向用户索取发行目录或复用已配置的 MCPY_RUNTIME_CATALOG，不虚构 URL。省略 --apk 时下载网易官方 APK，版本由 catalog 固定；新版或正式 APK 不能替换验证版本。默认资源目录为 ~/Library/Application Support/mcpy，可用 MCPY_ENGINE_HOME 隔离。无需 Homebrew、Wine、已安装的 Launcher 或 MPay 账号。终端交互运行 engine/run 有引导；AI 使用非交互和 JSON，不代替用户输入密码。

支持离线 Addon 世界和源码 Python Mod，使用既有项目构建/依赖能力。支持 cppconfig_protocol=1 的新运行包可按实例选择地形、模式、难度、种子及规则，见[实例世界设置](instance-world-settings.md)；旧运行包仍使用原来的平坦创造启动参数。默认重开最新实例，--new 新建；run --list 列出，run <ID前缀> 指定。项目 .runtime/macos/instances 保存世界，每个实例固定运行包与 APK。安装新版不会迁移原世界；发现版本不匹配时说明原因，不自动删除/重建。已有实例的 Mod 修改需先 stop 再 run，运行中再次 run 只返回现有会话。

run 返回进程启动，随后 status 的 world_ready=true 表示已观察到 HUD；还需验证客户端/服务端日志和实际玩法。日志使用 logs --source engine/game/worker。源码构建通过并不证明服务端 Mod 执行。

```sh
mcpy --local --project <项目> runtime py --session <sid> --side client --code "print('client probe')" --json
mcpy --local --project <项目> runtime py --session <sid> --side server --code "print('server probe')" --json
mcpy --local --project <项目> stop --session <sid> --json
```

客户端使用 launcher-jni，启动期间可以 --no-wait 提交并用 runtime py-result 按 request_id 查询；--wait-until 是无副作用的客户端 Python 就绪表达式。超时先查原请求，勿重复提交有副作用代码。服务端仍走原有 Safaia，仅进入世界后可用，不给服务端加客户端队列参数。runtime install/ui/player 继续通过公共客户端通道工作；注入的 mcpy.* 仍严格仅用于临时调试。

暂不支持本地 Map、联机服务器、MCS 身份、MCEditor 及 Windows screenshot/key/mouse/input-sequence/record。需要它们时使用显式 Windows --remote，不静默回退或尝试登录。macOS 前台 run 的 Ctrl+C 请求保存退出；一次性测试结束必须 stop 并确认进程退出，关闭自己创建的窗口。

编译目标为 macOS 11.0，游戏实测仅 26.6.2；包目前 ad-hoc 签名，未公证，不宣称已验证最低系统或 Gatekeeper。失败时提供实际错误及日志，不能建议全局关闭系统保护。


Windows 与 macOS 共用 PySide6 界面：人工使用 `mcpy --local --project <项目> ui`，或直接 run；Agent 仍用 --no-gui --detach --json。界面提供依赖管理、Mod 模板、实例、运行资源引导、Debug 日志、双端 Python、文件热更、自动监控、保存退出和重新部署重载世界。MCEditor 在 macOS 明确禁用。

`runtime watch --session <sid> --side client|server|both` 与 GUI 共用监控服务，停止监控保留游戏。模块热更只对已加载模块执行源码，修改实例方法、事件注册、新增入口或资源应保存重载世界，避免重复注册。both 仅适合可安全重复执行的公共模块。

新运行包声明 addon_link_protocol=1 时，行为包/资源包软链接到实例 assembled 目录，多依赖仍由统一组装器合并；不复制第二份运行包。旧运行包固定在原实例，保留复制兼容流程。Qt 与原生启动器有各自的系统下限：本机 Qt 6.11.2 的 Mach-O 最低 macOS 13.0，原生运行组件构建目标仍为 11.0，不能据此承诺整个 GUI 支持 11.0。

游戏启动后自动出现可折叠、可置顶的彩色日志小窗，与主界面共享会话、日志和监控。关闭小窗只隐藏视图；结束测试仍使用 stop 或“保存退出”，不能把小窗消失当成游戏已退出。新会话不要另起 studio_server_ui --port 监听器。

当前开发包 3.9.100.297020 的资源热更范围：已有微软粒子 JSON 更新后新建发射器已实测生效，回执仍只为 triggered/effect_verified=false；新增粒子文件未被识别时需重载世界。JSON UI 使用声明 json_ui_reload_protocol=1 的新运行包（local6 起），通过同一个 runtime reload ui 命令更新定义；旧包的 Ctrl+R 仍无效，安装新版后需显式启动新实例。原生重载会使现有自定义控件失效，此 APK 不触发 UiInitFinished；需按 Mod 原有逻辑重新 RegisterUI/CreateUI 和绑定回调，不使用旧控件句柄，也不把调试模块 _mcpy_launcher 写入业务代码。只验证了现有文件中的定义变化；新文件/复杂继承需单独验收。材质和 Metal Shader 仍返回 unsupported，不使用 ForceReloadResourcePack 绕过提示。True/triggered 只是已投递，不证明解析成功或界面已更新；错误 JSON 也可能被接受，需核对实际画面和文字。

日常开发和 AI 操作遵循 [Windows/macOS 公共无交互流程](local-development.md)，不需要编写平台专用脚本。上述安装与引擎限制是后端差异，run/status/logs/runtime/stop 的调用方式相同。
