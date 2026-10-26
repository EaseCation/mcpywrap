# 维护者：开发与验证

完整开发依赖安装为 `pip install -e ./core -e .`。仅工程核心环境使用 `pip install -e ./core`，并单独运行核心测试。共享 API、宿主能力和版本升级协议见 [shared-core.md](docs/shared-core.md)。

```powershell
python -X utf8 -m unittest discover -s tests -v
```

自动化测试使用临时目录、模拟安装/发布、Qt 离屏界面和模拟游戏进程，不启动真实游戏。

Windows 本地自动联机改动需运行 `test_windows_lan.py`、组/会话/调试通道回归，再按 [实机验收入口](tests/README.md) 验证 3.9、3.10 与多个项目。端口定位基于运行映像的 x64 指令结构；不得用固定 RVA、版本字符串或未验证的数值搜索替代唯一候选、进程身份及写前/写后校验。更新 Windows 菜单采集辅助程序后重新构建其 manifest；新的菜单动作必须有当前画面依据和有界的失败路径。

Windows 输入编排与游戏内队列共用 `timeline.py`，单次 key/mouse 与编排共用 `window.InputSender`。改动这些公共层时运行旧输入、编排及玩家队列回归；真实接收窗口和游戏 CLI 的时序验收见 [输入编排开发说明](tests/README.md#输入编排)。
测试进程使用UTF-8以保持文件读取和直接调用内部函数时的诊断输出一致；独立子进程另外验证真实CLI在GBK和UTF-8管道中的行为，不通过强制用户修改系统编码来掩盖兼容问题。
CLI 使用调用上下文传递项目目录；底层服务接受明确路径。不要为 GUI 切换全局工作目录。

有限命令返回数据或抛出错误，公共 CLI 层负责 JSON、stderr 和退出码。
新增命令使用相同入口，避免打印错误后返回成功。

Addon完整构建先组装再替换；Windows临时锁仅做有限重试。若安装与回滚同时失败，错误会报告保留的`.mcpy-build-*/previous`旧构建及目标目录。检查并解除占用后人工恢复；工具不自动删除或重放这类恢复目录。新产物已安装后的临时目录清理失败只记警告。

Skill 的辅助脚本只使用公开 CLI。游戏交互使用 Skill 当前推荐的公开入口；game_window 提供绑定会话的截图与桌面输入，Computer Use 仅用于允许占用前台的任务。
真实游戏验证请使用独立测试项目：

```powershell
python skills/mcpywrap/scripts/smoke.py --project D:\mods\test --game --expect-log "服务端已加载" --expect-log "客户端已加载"
```

脚本结束后停止自己创建的会话；日志和产物留在项目中。
需要手动截图验证时直接运行 `run --no-gui --detach --json`，保存会话 ID，操作完后显式 stop。
网络验证使用 `smoke.py --project <已有目录> --connect <地址> --expect-log <约定标记>`，不打包项目。单人与网络测试都可显式加 `--mcs-auth`；脚本停止自己创建的会话。
UI/玩家动作及服务端场景准备使用 [可选手动测试入口](tests/manual/runtime_controls/README.md)。这些脚本不参与默认 unittest/CI，不在正常游戏启动时执行；测试报告写到忽略的 `test/` 或仓库外目录，不提交过程记录。

录制自动化测试使用模拟任务和真实回环 HTTP，覆盖超过 64 MiB 的分块下载、内存上限、输入并行、清理保护和归档校验。真实 WGC／Media Foundation 验证在已登录未锁屏的 Windows 桌面显式运行：

```powershell
$env:MCPY_NATIVE_TESTS = '1'
python -X utf8 -m unittest discover -s tests -p test_native_recording.py -v
Remove-Item Env:MCPY_NATIVE_TESTS
```

该测试创建并清理自己的彩色窗口，验证固定帧率、黑帧、奇数尺寸、提帧与最小化；存在 ffprobe/ffmpeg 时额外交叉检查视频帧数、颜色和方向。真实游戏仍需通过公开 CLI 单独验收录制期间的输入及画面变化，不能用窗口测试代替。

`tests/manual_remote_recording.py --project <独立目录> --command <已安装mcpy路径>` 在本机回环启动带令牌的服务和自己的游戏，使用公开远程 CLI 验证录制、输入、游戏退出后的下载／提帧和删除，并清理游戏与服务。连接目标为本机 19132，不要求真实服务器，因此只验证捕获与传输，不声明进服成功；真实跨机器仍需分别在 Windows 和调用端验收。

发布见 [发布流程](RELEASING.md)。

局域网协议与路由测试使用 `tests/test_remote.py` 的真实回环 HTTP 和模拟游戏，不需要实际登录。
桌面原生实现集中在 `mcstudio/window.py`，Skill 脚本只组合公开 CLI。鼠标逻辑通过模拟 Win32 测试释放与坐标，实机效果按截图验证。
Windows CI 保留 3.9/3.12/3.14；macOS CI 验证 Qt 的延迟导入、Qt 离屏组件、本机构建与远程客户端。真实跨机测试需另行准备 Windows 桌面和 macOS 客户端。

游戏内 UI 的协议与有状态适配器测试见 `tests/test_runtime_ui.py`。在独立测试世界运行 `tests/manual_runtime_ui.py --project <目录> --session <会话> --output <新JSON> --require-background` 可通过公开 CLI 验证节点、后台滚动、点击音频页、主音量调整及恢复、旧快照拒绝与重复请求；运行前保持其他应用前台。脚本不停止传入会话，由创建者在结束后 stop。正式 UI 功能与内部引擎接口边界见 [runtime-ui.md](docs/runtime-ui.md)。

玩家操作与队列的状态机测试见 `tests/test_runtime_player.py`。`tests/manual_runtime_player.py` 使用已准备的独立生存世界验证进食、等待、选槽、朝向、蓄力射箭及重复请求；会消耗食物和箭，并恢复朝向、选槽。准备条件及参数见 [runtime-player.md](docs/runtime-player.md)。

## 项目脚本回归

用户契约见 [项目脚本](docs/project-scripts.md)。`project_scripts.py` 负责根项目任务与合作锁；`_script_worker.py` 是通过绝对路径启动的内部有限任务监督进程。低层 builder、Deployment.prepare/refresh 不自动执行 hooks。

`tests/test_project_scripts.py` 使用真实子进程、临时项目及模拟游戏启动，覆盖 JSON 透传、命令位置、串行失败、取消/超时、父进程被杀后的子进程清理和 native/Windows 准备入口。Qt 准备进度与所有权取消在 `test_qt_sessions.py` 中验证。Windows Job Object 路径须由 Windows CI/实机验证，macOS 测试不能替代。

## 消费者准备维护

`consumer_prepare.py` 从 DependencyService 的同一解析结果构建准备计划，`prepare_environment.py` 检查解释器并仅在 sync 创建缺失环境。Git 节点保留原始来源，工具从只读源码快照定位；注册的游戏导出目录不承担工具路径解析。

公共 `before` 执行根任务后运行消费者入口，阶段间检查配置、包身份和工具源码。CLI 构建和 worker 部署复用计划中的 manager；低层 builder 和 Deployment 不触发入口。启动预检保存摘要、任务描述和预算，worker 校验后执行，新增或变化的任务不能绕过预算。

消费者用法维护在 Skill 的 consumer-prepare 参考页，作者协议维护在 consumer-prepare-author 页。完整模板统一位于 Skill 的 assets/consumer-prepare，仓库 examples 仅保留导航。`tests/test_consumer_prepare.py` 将 Skill 单独复制到临时目录，通过其中的模板验证本地/Git 消费和只读查询；另使用真实 Git、虚拟环境和子进程验证协议，不声称游戏验收。实机验证程序显式运行，记录按平台区分。

可选验收程序 `python tests/manual/consumer_prepare_acceptance.py --output <尚不存在的证据目录>` 复制示例并验证 sync、查询、build/package 和输入更新；加 `--game` 才启动当前平台的独立游戏，检查新启动一次、复用零次和重启一次。`--game --clients 2` 检查主机一次、客机补齐零次和整组重启一次。脚本只清理本次独立夹具的会话，保留世界和报告；不会把进程生命周期验证标记成多人玩法或连接成功。Windows/macOS 分别运行，不接入默认 CI。

## 图标资源

使用 `python scripts/build_app_icon.py` 重建 PNG 和 ICNS，需要本机 Xcode 27 / Icon Composer 27 与 PySide6。保留可编辑分层源；运行时直接使用静态资源，不要求用户安装 Xcode。图标的产品与格式约定见 [Qt 界面](docs/qt6-development.md#应用图标)。

## 文档与 Skill 的维护边界

面向用户和 AI 的命令用法以 `skills/mcpywrap/SKILL.md` 及其 references 为单一维护来源。主文件只保留调用契约、任务路由和影响决策的共通边界；每篇参考围绕一个实际任务，可独立完成该任务，不以源码模块或提交批次划分文章。参数以公开 CLI 帮助和目标能力核对，旧协议留在兼容入口。

修改公开能力时，更新对应的唯一参考页和必要的主文件路由；README 与 docs 中的用户入口指向它，不复制整份操作流程。验证参考链接可在单独复制的 Skill 中使用，示例能经公开 CLI/配置解析，简单任务不必读取安装、调试、录制等无关章节。Skill 测试应验证示例/协议行为，不锁定段落措辞。

`docs/` 只保存现行产品、架构、接口契约及兼容性说明，不放开发过程文档。维护与发布流程分别放在根目录 CONTRIBUTING.md、RELEASING.md，可复用测试指南与程序留在 tests。临时计划、竞品调研、逐轮审计、推进状态、机器路径与当次验收日志放入 Git 忽略的 `.local-notes/` 或 `test/`。这些目录同时被 sdist 排除，发布检查不得把本地工作笔记当必需文件。
