# 维护者：开发与验证

```powershell
python -X utf8 -m unittest discover -s tests -v
```

自动化测试使用临时目录、模拟安装/发布、Qt 离屏界面和模拟游戏进程，不启动真实游戏。

Windows 输入编排与游戏内队列共用 `timeline.py`，单次 key/mouse 与编排共用 `window.InputSender`。改动这些公共层时运行旧输入、编排及玩家队列回归；真实接收窗口和游戏 CLI 的时序验收见 [输入编排开发说明](input-sequence.md#验证)。
测试进程使用UTF-8以保持文件读取和直接调用内部函数时的诊断输出一致；独立子进程另外验证真实CLI在GBK和UTF-8管道中的行为，不通过强制用户修改系统编码来掩盖兼容问题。
CLI 使用调用上下文传递项目目录；底层服务接受明确路径。不要为 GUI 切换全局工作目录。

有限命令返回数据或抛出错误，公共 CLI 层负责 JSON、stderr 和退出码。
新增命令使用相同入口，避免打印错误后返回成功。

Addon完整构建先组装再替换；Windows临时锁仅做有限重试。若安装与回滚同时失败，错误会报告保留的`.mcpy-build-*/previous`旧构建及目标目录。检查并解除占用后人工恢复；工具不自动删除或重放这类恢复目录。新产物已安装后的临时目录清理失败只记警告。

Skill 的辅助脚本只使用公开 CLI。游戏交互优先使用 runtime ui/player；game_window 提供绑定会话的截图与桌面输入，Computer Use 仅用于允许占用前台的任务。
真实游戏验证请使用独立测试项目：

```powershell
python skills/mcpywrap/scripts/smoke.py --project D:\mods\test --game --expect-log "服务端已加载" --expect-log "客户端已加载"
```

脚本结束后停止自己创建的会话；日志和产物留在项目中。
需要手动截图验证时直接运行 `run --no-gui --detach --json`，保存会话 ID，操作完后显式 stop。
网络验证使用 `smoke.py --project <已有目录> --connect <地址> --expect-log <约定标记>`，不打包项目。单人与网络测试都可显式加 `--mcs-auth`；脚本停止自己创建的会话。
UI/玩家动作及服务端场景准备使用 [可选手动测试入口](../tests/manual/runtime_controls/README.md)。这些脚本不参与默认 unittest/CI，不在正常游戏启动时执行；测试报告写到忽略的 `test/` 或仓库外目录，不提交过程记录。

录制自动化测试使用模拟任务和真实回环 HTTP，覆盖超过 64 MiB 的分块下载、内存上限、输入并行、清理保护和归档校验。真实 WGC／Media Foundation 验证在已登录未锁屏的 Windows 桌面显式运行：

```powershell
$env:MCPY_NATIVE_TESTS = '1'
python -X utf8 -m unittest discover -s tests -p test_native_recording.py -v
Remove-Item Env:MCPY_NATIVE_TESTS
```

该测试创建并清理自己的彩色窗口，验证固定帧率、黑帧、奇数尺寸、提帧与最小化；存在 ffprobe/ffmpeg 时额外交叉检查视频帧数、颜色和方向。真实游戏仍需通过公开 CLI 单独验收录制期间的输入及画面变化，不能用窗口测试代替。

`tests/manual_remote_recording.py --project <独立目录> --command <已安装mcpy路径>` 在本机回环启动带令牌的服务和自己的游戏，使用公开远程 CLI 验证录制、输入、游戏退出后的下载／提帧和删除，并清理游戏与服务。连接目标为本机 19132，不要求真实服务器，因此只验证捕获与传输，不声明进服成功；真实跨机器仍需分别在 Windows 和调用端验收。

发布见 [发布流程](releasing.md)。

局域网协议与路由测试使用 `tests/test_remote.py` 的真实回环 HTTP 和模拟游戏，不需要实际登录。
桌面原生实现集中在 `mcstudio/window.py`，Skill 脚本只组合公开 CLI。鼠标逻辑通过模拟 Win32 测试释放与坐标，实机效果按截图验证。
Windows CI 保留 3.9/3.12/3.14；macOS CI 验证 Qt 的延迟导入、Qt 离屏组件、本机构建与远程客户端。真实跨机测试需另行准备 Windows 桌面和 macOS 客户端。

游戏内 UI 的协议与有状态适配器测试见 `tests/test_runtime_ui.py`。在独立测试世界运行 `tests/manual_runtime_ui.py --project <目录> --session <会话> --output <新JSON> --require-background` 可通过公开 CLI 验证节点、后台滚动、点击音频页、主音量调整及恢复、旧快照拒绝与重复请求；运行前保持其他应用前台。脚本不停止传入会话，由创建者在结束后 stop。正式 UI 功能与内部引擎接口边界见 [runtime-ui.md](runtime-ui.md)。

玩家操作与队列的状态机测试见 `tests/test_runtime_player.py`。`tests/manual_runtime_player.py` 使用已准备的独立生存世界验证进食、等待、选槽、朝向、蓄力射箭及重复请求；会消耗食物和箭，并恢复朝向、选槽。准备条件及参数见 [runtime-player.md](runtime-player.md)。
