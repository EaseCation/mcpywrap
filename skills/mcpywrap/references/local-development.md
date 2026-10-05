# Windows/macOS 本地无交互开发与验收

适用于本地 Addon 世界。对两个平台使用相同命令、参数、JSON 解析和生命周期；后端选择由 mcpy 完成。安装来源仍有区别：Windows 通过 MC Studio 准备引擎；Apple Silicon 通过 engine install 准备原生运行包/APK，见 [macOS 安装](macos-local.md)。不支持的功能明确报告，不自动换平台、登录或切到桌面输入。

## 纯命令契约

统一前缀：`mcpy --local --project <绝对项目目录> --non-interactive`，以下每条有限命令最后添加 `--json`。全局参数在子命令前。stdout 是单个 JSON，stderr 可含构建诊断；同时检查退出码、ok、state、error、hint，不从退出码零推断游戏业务效果。

这里“无头”是 mcpy 控制端无需 Qt 管理页、日志小窗、TUI 或人工点击。Minecraft 仍有原生窗口并需要图形会话/GPU。不要承诺 SSH 无显示服务运行或游戏无渲染模式。不要把 `--no-gui` 当成隐藏游戏窗口。

| 步骤 | 公共命令 | 结果检查 |
|---|---|---|
| 安装能力 | `doctor --capabilities` | CLI/宿主具备需要的能力 |
| 运行资源 | `doctor` | ok=true；否则根据 hint 准备资源，不循环启动 |
| 构建 | `build` | 组装成功只证明文件构建，不证明 Mod 已运行 |
| 启动/复用 | `run --no-gui --detach` | 保存 session；需要独立验收世界才加 --new |
| 会话能力 | `runtime capabilities --session <sid>` | schema_version=1，control.available；reload 各项 state |
| 状态/找回 | `status --session <sid>` / `status --list` | running 仅表示进程存活；丢失启动响应先找回 |
| 日志 | `logs --session <sid> --source game --tail 200` | source 还可为 engine/worker；检查双端 Mod 标记 |
| 客户端 Python | `runtime py --session <sid> --side client --file <脚本.py>` | state=completed，side=client，检查 stdout/stderr/value/error |
| 服务端 Python | `runtime py --session <sid> --side server --file <脚本.py>` | 同上，side=server；只用于自己的本地世界 |
| Python 热更 | `runtime reload python --session <sid> --side client --module Mod.client.logic` | 模块必须已加载；服务端模块用 --side server |
| JSON UI 热更 | `runtime reload ui --session <sid>` | triggered 仅代表请求已投递；须重新创建 UI 并核对文本/效果 |
| 粒子/材质/Shader | `runtime reload <kind> --session <sid> --file <资源文件>` | 先看当前会话对应能力与限制 |
| 结束会话 | `stop --session <sid>` | 确认 exited；失败时保留并报告，不批量强杀 |

macOS 原生后端的 stop 请求保存后退出；Windows 沿用现有进程停止机制，不能将退出成功当作新增的存档保存保证。需要保留重要存档时，先通过游戏正常退出世界。

`runtime capabilities` 只读本机会话和运行包声明，不调用游戏代码，不暴露内部控制凭据。available 表示入口允许调用，尚未证明游戏就绪、具体 API 存在或资源生效。unsupported 应按 reason 处理；unavailable 先核对会话/worker。旧 worker 的 client_queue 可能为 null，不能当成支持。远端仍用 doctor --capabilities；本地会话能力查询不静默回退远端/本机。

基线全部使用同步 `runtime py`。启动期异步队列只在 python.client_queue=true 时使用；不要把 macOS 特有的队列要求加到 Windows/远端公共流程。unknown/queued/running 的请求不重复提交有副作用脚本；支持队列的会话通过原 request_id 查询，其他会话保留证据并检查日志。server reload 还需 python.reload_sides 包含 server。

## 就绪与验收脚本

首次执行业务验收前，用同一客户端通道检查已进入世界和 HUD。以下是只读探针，可以间隔轮询并设置截止时间：

```python
try:
    import mod.client.extraClientApi as api, gui
    _result = api.GetLevelId() not in (None, -1, '-1') and gui.get_top_screen() == 'hud_screen'
except (ImportError, AttributeError):
    _result = False
```

True 仍不证明服务端 Mod 正常。客户端/服务端分别使用日志标记、断言和 `_result` 验收；游戏脚本为 Python 2，文件 UTF-8。脚本抛出异常或结果未确认时停止，不自动重放任意代码。

需要可重复的一次性验收时复用技能的 smoke.py：

```sh
python <skill>/scripts/smoke.py --command <bootstrap返回的mcpy路径> --project <项目> --local --game --client-file <客户端验收.py> --server-file <服务端验收.py> --expect-log <Mod加载标记> --timeout 90
```

该脚本通过公共 CLI 打包并新建独立世界，等待世界就绪，两个脚本各执行一次，收集日志和结构化结果，finally 中停止自己启动的会话。任一验收失败整体返回非零；unknown 不重试脚本。仅需日志时省略脚本；仅需构建打包时省略 --game。需要保留游戏或复用现有世界时使用命令表，不使用这个自动关闭的脚本。

## UI 重载和后台操作

JSON UI 重载的是定义集合，`--file` 不表示只刷新一个控件。可能使原控件句柄、临时状态和回调绑定失效；通过 Mod 原有入口重新 RegisterUI/CreateUI、绑定回调，再比较新标签文字或行为。当前 macOS 开发包不触发 UiInitFinished，不能等待它自动恢复；不要全局伪造该事件，也不要把 `_mcpy_launcher` 写进业务 Mod。不要把返回 True 当成 JSON 有效性或重载完成证明。

实际效果可用正式 Label.GetText、业务计数等验证；禁止先 SetText 再把显示变化当成 JSON 热更成功。重复刷新前确保上一次定义加载及 UI 重建完成，重新获取控件。新增文件或复杂继承不生效时报告范围，保留日志，按需保存并重载世界。

操控 UI/玩家时使用 `runtime install` → `runtime ui/player`。按 [UI 节点流程](runtime-ui.md) 获取新快照，使用节点 ID，不需要桌面输入。UI 无法表达的画面或截图需求再查看实际平台能力；macOS 不支持 Windows 桌面 screenshot/key/mouse/record。`runtime watch` 是持续的纯终端 Python 自动热更命令，不加 --json；资源变化提示手动重载，不自动重建业务 UI。结束监控后还要停止自己启动的游戏。

不同测试实例可使用独立的世界设置；创建参数、模板导入及保存语义见[实例世界设置](instance-world-settings.md)。
