# 维护者：开发与验证

```powershell
python -X utf8 -m unittest discover -s tests -v
```

自动化测试使用临时目录、模拟安装/发布、Qt 离屏界面和模拟游戏进程，不启动真实游戏。
测试进程使用UTF-8以保持文件读取和直接调用内部函数时的诊断输出一致；独立子进程另外验证真实CLI在GBK和UTF-8管道中的行为，不通过强制用户修改系统编码来掩盖兼容问题。
CLI 使用调用上下文传递项目目录；底层服务接受明确路径。不要为 GUI 切换全局工作目录。

有限命令返回数据或抛出错误，公共 CLI 层负责 JSON、stderr 和退出码。
新增命令使用相同入口，避免打印错误后返回成功。

Addon完整构建先组装再替换；Windows临时锁仅做有限重试。若安装与回滚同时失败，错误会报告保留的`.mcpy-build-*/previous`旧构建及目标目录。检查并解除占用后人工恢复；工具不自动删除或重放这类恢复目录。新产物已安装后的临时目录清理失败只记警告。

Skill 的 bootstrap、smoke 脚本只使用公开 CLI；Skill 的 game_window 脚本负责绑定会话的截图和键盘输入；复杂交互使用环境的 Computer Use。
真实游戏验证请使用独立测试项目：

```powershell
python skills/mcpywrap/scripts/smoke.py --project D:\mods\test --game --expect-log "服务端已加载" --expect-log "客户端已加载"
```

脚本结束后停止自己创建的会话；日志和产物留在项目中。
需要手动截图验证时直接运行 `run --no-gui --detach --json`，保存会话 ID，操作完后显式 stop。
网络验证使用 `smoke.py --project <已有目录> --connect <地址> --expect-log <约定标记>`，不打包项目。单人与网络测试都可显式加 `--mcs-auth`；脚本停止自己创建的会话。
历史验收记录仅用于追溯，不能代替当前版本测试。

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
Windows CI 保留 3.9/3.12/3.14；macOS CI 验证无 Qt 安装、本机构建与远程客户端。真实跨机验收需另行准备 Windows 桌面和 macOS 客户端。
