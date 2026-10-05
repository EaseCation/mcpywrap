# 可选手动测试：游戏内 UI、玩家输入和服务端验证

**仅在显式运行下列脚本时执行。不会被默认 unittest、CI、`mcpy run` 或普通项目启动自动执行。**

默认单元测试 `tests/test_runtime_ui.py`、`test_runtime_player.py` 等用模拟游戏 API 验证协议、状态机和释放逻辑。这里调用真实会话的公开 CLI，实际操作游戏，并用服务端读回检查效果。桌面 SendInput/WGC/录制仍是独立的 Windows 专用测试，不属于本套件的 macOS 覆盖。

## 文件与职责

| 文件 | 用途 |
|---|---|
| `run.py` | 可选入口，启动新的测试世界或附加已有会话；按实例能力执行/跳过，每个用例输出 passed/failed/skipped |
| `support.py` | 公开 CLI 的 JSON 调用，按原 request_id 查询 macOS queued/running Python 结果；不重发有副作用源码 |
| `client_probe.py` | 游戏客户端脚本，检查当前 `mcpy.ui`、`mcpy.player`、SDK 别名及世界 |
| `server_fixture.py` | **显式启用的服务端夹具**：测试平台、饥饿/物品准备、靶实体、伤害事件记录、方块效果读回与实体/监听清理 |
| `movement.json` | 十步游戏内移动、疾跑、按键、潜行、跳跃及朝向队列 |
| `../../manual_runtime_ui.py` | UI 点击、滚动、音量滑块、旧快照拒绝、重复请求及音量恢复 |
| `../../manual_runtime_player.py` | 进食/射箭、幂等请求、朝向/槽位恢复；可单独对已准备的测试世界使用 |

安装的临时客户端扩展来自产品的 `mcpywrap/mcstudio/runtime_ui_payload.py`、`runtime_ui_outline.py`、`runtime_player_payload.py`，由 `runtime install` 注入，不在此目录复制一份实现。**`mcpy.*` 只供调试，不能成为业务 Addon 的依赖。** 服务端夹具同样不属于业务包，不需要复制到行为包中。

## macOS：显式运行

使用安装了当前 mcpywrap 的同一个 Python 环境（源码安装通常为 `.venv/bin/python`）。若通过 uv tool 安装，可先设置 `manual_python="$(uv tool dir)/mcpywrap/bin/python"`，将下方 `python` 替换为 `"$manual_python"`，避免误用没有安装 mcpywrap 的系统 Python。先准备 Apple Silicon 本地运行包和匹配资源，检查 `mcpy --local engine doctor --json`；没有默认资源源时，按发行方 catalog 配置安装。下面的测试只针对本地 Addon 世界。

在仓库根目录或手动测试 ZIP 解压目录执行（替换项目路径）：

```sh
mkdir -p "$HOME/mcpy-manual-project"
python -m mcpywrap --local --project "$HOME/mcpy-manual-project" --non-interactive init --name manual-controls --type addon --json
python -m mcpywrap --local --project "$HOME/mcpy-manual-project" --non-interactive mod --name ManualControls --json

# 先做双端探针，不操作 UI，不修改世界场景。
python tests/manual/runtime_controls/run.py --project "$HOME/mcpy-manual-project" --launch --suite probe

# 完整用例：必须显式允许服务端改变独立测试世界。
python tests/manual/runtime_controls/run.py --project "$HOME/mcpy-manual-project" --launch --suite all --prepare-fixture
```

`--launch` 每次新建测试世界，脚本结束时停止它创建的会话。自动监控和其他调试程序不要同时向同一会话发送脚本。

若需保留游戏观察，可先自行启动，再传入 session：

```sh
python -m mcpywrap --local --project "$HOME/mcpy-manual-project" --non-interactive run --new --no-gui --detach --json
python tests/manual/runtime_controls/run.py --project "$HOME/mcpy-manual-project" --session SESSION_ID --suite ui
python tests/manual/runtime_controls/run.py --project "$HOME/mcpy-manual-project" --session SESSION_ID --suite player --prepare-fixture
# 附加模式不会关闭传入会话，由创建者在检查后停止。
python -m mcpywrap --local --project "$HOME/mcpy-manual-project" stop --session SESSION_ID --json
```

## 用例与结果

`--suite probe` 是默认值。`ui` 操作原生设置界面并恢复音量；支持中文/英文常见控件名称，其他语言/布局不猜测节点。`player` / `all` 必须传 `--prepare-fixture`，使用一个玩家、主世界、本地测试会话；不会修改网络服务器。

玩家用例涵盖进食/普通弓射箭及物品消耗、连续移动与释放、攻击生命值变化、服务端 projectile 伤害事件、放置和挖掘。服务端读回用于证明实际效果，客户端 completed 不单独作为效果证明。

`--prepare-fixture` 会覆盖玩家附近测试平台范围的方块，改变位置、游戏模式、饥饿值和快捷栏，创建/删除靶实体。清理只释放本套件输入、恢复朝向/槽位、移除自建实体/监听；**不恢复地形、模式、物品和消耗**，所以只能使用可丢弃的独立测试世界。

报告默认保存在项目忽略目录 `.runtime/manual-tests/<id>.json`；可用 `--output /path/outside/repo/result.json` 指定新路径。入口汇总所有用例，UI/进食助手另保存 JSON 和日志；不覆盖旧报告，不将结果或开发过程记录提交到仓库。`failed` 或清理失败返回非零；`skipped` 单列，不代表该能力已经验证。

macOS 通过游戏内 Python/API 控制，**不需要为本测试额外开启桌面辅助功能或录屏权限**。原生 UI/玩家私有 API 是否存在由实际引擎决定，HBUI/HTML 或缺失接口明确跳过/报错，不回退到桌面键鼠。macOS 的 `--require-background` 不支持；此选项只在 Windows 通过前台 PID 采样取证。省略该选项不证明后台隔离。Windows 游戏动作与服务端场景可复用同一入口；macOS 的实际结果需要在对应运行包上执行本套件确认。

默认测试仅对调用端排队结果处理和显式启用标记做模拟检查，不调用游戏 SDK或启动实机。没有要求普通用户运行这些测试，也没有把它们加入发布/CI 的自动游戏步骤。
