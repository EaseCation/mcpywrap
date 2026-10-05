---
name: mcpywrap
description: 使用 mcpywrap 管理《我的世界》中国版 Addon/地图、依赖和 QuMod，并在 Windows 本机/远程或 Apple Silicon macOS 本地离线会话中调试、读取 UI 节点和操控玩家；桌面截图/输入/录制仅 Windows。注入的 mcpy.* 仅限调试，禁止用于业务代码。
---

# mcpywrap

使用公开 CLI；无需通读仓库 docs、CLAUDE.md 或源码。先确定项目操作发生在哪台机器，以及游戏使用 Windows 本机、Windows 远程还是 Apple Silicon macOS 本地后端。通过同一套 run/status/logs/stop/runtime 接口操作，先读取 doctor --capabilities 的实际能力。

## Windows/macOS 共用的纯命令开发入口

本地 Addon 开发默认采用同一套命令，不按平台编写两份启动/调试/热更流程。AI 使用 `--local --project <目录> --non-interactive`，启动必须显式使用 `run --no-gui --detach --json`。人工交互式 `run` 默认显示日志和热更调试小窗；AI 使用 --no-gui 明确抑制小窗。macOS 首次运行自动安装资源并在 stderr 显示进度；`mcpy ui` 打开完整项目管理页。无需操作 Qt/TUI 或原生窗口；游戏仍需要图形会话和 GPU，这不是无显示服务运行。

先读 [本地无交互开发与验收](references/local-development.md)：涵盖会话能力查询、就绪检查、双端 Python、JSON UI 重载、日志及保存退出。`runtime capabilities --session <sid> --json` 返回当前实例的能力，不能仅从宿主平台推断；旧实例固定旧运行包。优先公共 CLI，不直接调用 `_mcpy_launcher`、JNI、Safaia 或读取控制凭据。

## 强制边界：mcpy.* 仅限临时调试

**严禁在任何业务代码中使用或依赖 `mcpy.*`，包括 `mcpy.ui`、`mcpy.player`、`mcpy.api` 及其别名、封装或间接调用。** 这些能力仅在执行 `runtime install` 后临时注入当前调试会话；正常启动或发布后的游戏运行环境中不存在，不是 ModSDK，也不是可分发的游戏依赖。

本文及参考文档中的 `mcpy.*` 示例只供 Agent 通过 `runtime py` 执行临时探针、观察和测试操作。不得复制进 Mod、Addon、客户端/服务端业务模块或任何随游戏发布的脚本，也不得把注入或安装控制层作为业务运行的前置条件。业务功能必须使用目标引擎正式支持的 ModSDK 或项目已有框架；例如 `mcpy.api` 的调用须改为正式导入相应端的 SDK。提交或打包业务改动前，检查新增代码未引入上述调试依赖。命令行工具 `mcpy` 不受此 Python 命名空间限制。

## 按任务选择控制入口

| 当前任务 | 入口与下一步 | 前台要求 |
|---|---|---|
| 理解界面、点按钮、滚动或调滑块 | `runtime ui snapshot` → 阅读节点树 → 单次节点动作 → 新快照；[UI 说明](references/runtime-ui.md) | 后台可用 |
| 移动、看向、切槽、攻击、进食、射箭 | `runtime player snapshot`；已知连续动作优先 `runtime player sequence`，见下方方法表 | 后台可用 |
| 测量 Windows 键鼠快切的 0–20 ms 提交间隔 | `input-sequence --file <计划.json>`；读 [时间编排](references/input-sequence.md) | 会激活游戏，须允许占用前台 |
| 只需一次 Windows 按键或鼠标动作 | `key` / `mouse`；不能用多次 CLI 调用代替毫秒编排 | 会激活游戏 |
| 节点无法表达当前画面（如 HBUI） | `screenshot --background-only` 补图；不足时报告限制 | 不自动抢焦点 |

`runtime ui/player` 需先 `runtime install`，Windows `input-sequence/key/mouse` 不需注入。两种序列共用排时规则，但 API 动作不等于 Windows 键鼠事件。`completed / accepted / sent` 说明调用或提交状态，业务效果仍须用新快照、日志或录像验证。

## 安装与前置检查

- macOS 后端、Qt6 和会话能力查询要求 CLI 0.4.0+；候选版未上 PyPI 时按仓库验收文档安装对应 wheel，不把已更新的 Skill 当作 CLI 已升级。
- Skill 文件夹和 CLI 分别安装，更新一端不会自动更新另一端。两台机器都复制完整 Skill，并在各自机器上检查 CLI。
- 使用已有 uv 运行 `uv run --no-project --python 3.12 "<skill>/scripts/bootstrap.py"`，无需假定 PATH 中存在 `python`；Windows 也可用 [bootstrap.ps1](scripts/bootstrap.ps1)。
- 默认复用已有安装；更换来源需 `--upgrade`，可选 `--version`、`--git-ref <完整 SHA>`、`--editable-path <本机目录>`。PowerShell 对应 `-Upgrade/-Version/-GitRef/-EditablePath`。
- 使用本机 bootstrap 返回的 `command` 执行后续 CLI；示例中的 `mcpy` 均指这个路径，不跨机器复用它。
- Windows 服务端：bootstrap 加 `--local --require-capability serve`，再用 `mcpy --local doctor --capabilities --json`。需要登录时额外检查 `mcs-auth` 组件并由用户登录 MCS。
- Apple Silicon macOS 本地：bootstrap 加 `--local --require-capability macos-local-worlds`，再用 `mcpy --local engine doctor --json` 检查资源。安装和限制见 [macOS 本地测试](references/macos-local.md)。资源未就绪时 run 会从内置发行源自动安装；也可提前执行 engine install。安装成功仍须验证游戏就绪。
- macOS 远程端：bootstrap 加 `--remote <地址> --require-capability remote-client --require-capability network-sessions`；后台操作再要求调用端 `runtime-ui/runtime-player` 与执行端 `py`，截图要求 `screenshot`。桌面单次输入要求 `key/mouse`，Windows 编排要求 `input-sequence`，可重复传入 `--require-capability`。
- 本机能力看 `local_capabilities`，Windows 服务能力看 `remote.capabilities`。`remote.ok=false` 时停止远程流程；组件具备不表示已登录、窗口已就绪或已进服。
- `bootstrap --remote` 只做检测，不保存路由。每次远程调用明确传 `--remote <endpoint>`，或确认当前进程确实继承了 `MCPY_REMOTE`；不依赖上一次终端调用的 export。
- 先检查相关 `--help` 和能力；不要把新版 Skill 配上旧 CLI 后猜参数。统一注入、UI/玩家封装和严格后台截图需调用端 CLI 0.3.17+；执行端须支持 `py`，远程严格后台截图还须执行端 0.3.17+。局域网细节见[远程测试](references/remote-testing.md)。
- 统一时间编排需调用端 CLI 0.3.19+；更新 CLI 后对已有游戏会话重新 `runtime install`。Windows `input-sequence` 的远程执行端也需 0.3.19+ 并报告该能力；不要把旧版 `sequence` 已存在当成支持 `at_ms`。
- Git项目依赖和框架快捷添加从0.3.8提供；bootstrap分别用 `--require-capability git-dependencies`、`--require-capability framework-presets` 检查，不以版本号0.3.7推断具备。缺失时显式选择包含这些能力的版本或源码安装。

## 执行位置与参数

全局参数放在子命令之前：`mcpy --project "<本机已有目录>" --remote <地址> --non-interactive <命令> --json`。
路由优先级为 CLI → `MCPY_REMOTE` → 本机项目 `[tool.mcpywrap].remote_url`；`--local` 强制本机执行。远端失败不回退。

| 操作 | 执行位置 |
|---|---|
| init/add/remove/mod/modsdk/sync/build/package/dev/publish | 调用端本机，配置远端后也不迁移项目文件 |
| doctor/connect/status/logs/stop/screenshot/key/mouse/input-sequence、record、runtime py | 配置的 Windows 服务；没有远端配置则由本机后端处理，桌面截图/输入仅 Windows |
| runtime ui | 调用端封装，通过同一会话的 client Python 通道在游戏内执行 |
| runtime player、runtime install | 同上；一次注入 UI、玩家动作和客户端 API 简写 |
| runtime reload、runtime watch | Windows 或 Apple Silicon macOS 本地测试世界，显式使用 --local |
| 配置服务器目标的 run | 本机校验项目与依赖，远端只连接服务器 |
| 本地世界 run、实例管理 | Windows 或 Apple Silicon macOS 本机，明确使用 `--local`；macOS 目前仅 Addon，远端不支持世界实例 |
| ui | Windows/macOS 的共用 PySide6 界面，仅供人工操作；Agent 仍用 CLI |
| serve、edit | Windows 本机；macOS 不支持 MCEditor |

`--project` 必须是调用端路径且目录已存在；纯连接不需要 init。远程实际会话保存在 Windows 的 serve 数据目录。
远程结果中的 `project/image` 是调用端路径；`remote_project/executable/log_path/engine_log_path` 是 Windows 信息。读取远程日志用 logs，不在 macOS 打开 Windows 路径。

Windows/macOS 共用依赖锁；克隆后用 `sync --json` 恢复，旧平台格式自动验证和备份。向用户说明依赖名称与下一步命令，完整迁移信息保留在 JSON 中。

## 项目工作流

有限命令使用 `--non-interactive --json`，检查退出码和 `ok/error/hint`；保留用户已选择的项目路径与配置。

| 任务 | 子命令 |
|---|---|
| 新建／接入 | `init --name demo --type addon` 或 `--type map` |
| 包依赖 | `add "package-name>=1.0"` / `remove package-name` |
| 本地 Addon 引用 | `add --path ../common` / `remove --path ../common` |
| Git 项目依赖 | `add --git <URL> --ref <提交或标签>` / `remove --git <依赖名>` |
| QuMod 快捷添加（仍是 Git 依赖） | `add --qumod --script-dir MyMod`；等价于 `add --framework qumod --script-dir MyMod` |
| 模板／SDK | `mod --name DemoMod` / `modsdk --version <版本>` |
| 构建／ZIP | `build` / `package`；地图要合并资源时用 `package --merge` |
| 同步／安装项目 | `sync` / `sync --install` |
| 为用户打开编辑器 | Windows 本机 `edit --detach`；启动不等于界面任务完成 |

初始化不覆盖已有配置、不隐式安装 SDK 或依赖。本地引用选 Addon 根目录，无需先初始化，不自动成为可分发包依赖。

依赖操作前先区分来源；Git、QuMod、克隆恢复和版本管理任务读[Git 依赖与快捷添加](references/project-dependencies.md)：

- `add <Python包>` 安装到工具 Python 环境；没有识别出的 Addon 内容会标为“仅开发环境”，不会进入游戏产物。`sync --install` 的额外安装步骤及 ModSDK 补全库也属于工具环境。
- `add --path` 引用本地 Addon；`add --git` 获取并注册远程项目，依据项目描述或明确布局组装游戏代码与资源。它们不是向游戏执行 pip install。
- QuMod 是 Git 依赖的快捷预设。新脚本目录会生成入口，已有业务代码保留；不要为了使用快捷命令先创建一套原生 Mod 模板，也不要把上游源码复制进业务仓库。
- 克隆已配置项目后优先执行一次 `sync`，不要重新 `init` 或重复 `add`。这恢复依赖，不下载引擎，也不保证全部工具环境依赖已安装。

游戏使用内置 Python，不读取工具环境的 site-packages；原生扩展或依赖外部安装步骤的库不能直接用于游戏。处理 import 错误时检查组装后的代码和加载入口，不通过反复 pip 安装框架解决。
构建时主项目优先；检查 package 返回的 `artifact`。`dev` 持续输出文本，不用 JSON；依赖声明变化后重启监控。
网易Add-on生产包用公开 `mcpy package` 导出，不自行重压缩或更改包名。打包器需保留行为包entities空目录以满足平台结构检查；仅脚本Addon不应为此创建虚构实体。发布前检查实际ZIP，旧CLI可能尚未包含此修复；本地加载或上传201不证明平台自测通过。
检查 ZIP 的实际内容及游戏脚本加载日志；pip 安装、系统 Python 导入或构建成功都不能代替游戏验收。`publish` 的 PyPI 分发与游戏 ZIP 分发不同。
涉及具体玩法时，原版 API、事件、枚举和 JSON 组件须查证目标网易版本；不能套用 Java 版或通用 Bedrock 的名称。若提供了 netease-modsdk MCP，可查询精确接口、端侧、参数和备注；未查到的能力明确标为未验证。
`publish --yes` 仅在用户请求真实上传时调用；卸载和实例删除也需相应明确选项。

## 游戏会话

新建不同地形、难度、种子或游戏规则的测试实例时，读[实例世界设置](references/instance-world-settings.md)。使用 `run --new` 的直接参数，无需先创建再修改文件；世界设置属于实例，不写入项目 pyproject.toml。

Windows 用户在专用、已登录未锁屏的桌面设置 `MCPY_REMOTE_TOKEN` 后运行 `mcpy --local serve` 并保持控制台打开；默认 `0.0.0.0:18765`，不加 `--json`。
远程首次设置按需读[远程测试](references/remote-testing.md)，不要把监听地址 0.0.0.0 当作客户端地址。

| 目标 | 启动命令 |
|---|---|
| Windows/macOS 本地 Addon 世界（先准备资源） | `mcpy --local --project "<项目>" --non-interactive run --no-gui --detach --json` |
| 远程临时服务器 | `mcpy --remote <Windows服务地址> --non-interactive connect <游戏服务器地址> --port 19132 --detach --json` |
| 远程项目目标 | `mcpy --remote <地址> --project "<调用端项目>" --non-interactive run --detach --json` |

固定游戏目标在项目 `[tool.mcpywrap.server]` 填 `host/port`。连接不装配本地 Mod，网络模式不支持 Map、`--new` 或世界实例 ID。
远程机器路径只在 Windows serve 参数中配置，客户端仅可覆盖 `--engine-version`；本机 connect 可使用原有引擎覆盖参数。
`MCPY_REMOTE_TOKEN` 是服务默认要求的访问令牌；可信网络可显式用 `mcpy --local serve --no-token` 关闭认证，此时忽略已有令牌，可访问该端口的设备均可执行游戏客户端 Python。先检查 `serve --help` 是否支持该参数。`--mcs-auth` 才是本次游戏的 MCS 登录身份，二者互不替代。仅用户要求登录身份时添加该选项。

1. 保存启动返回的 `endpoint`（远程时）、`project`、`session`、进程身份和日志位置；后续操作始终绑定相同 endpoint 与 session。
2. 用相同全局参数调用 `status --session <id> --json`、`logs --session <id> --source game --tail 100 --json`；source 也可选 engine/worker。
3. `running/identity_provided/sent` 只说明对应阶段；Mod 加载、进服、交互效果分别用日志标记或截图确认。
4. 一次性测试结束 stop；用户要求保留时报告会话 ID。busy 时先列举，不停止不属于本任务的会话。

启动响应丢失用相同 endpoint 的 `status --list --json` 找回；输入超时不盲目重试。
人工交互式本地 run 默认显示紧凑的彩色日志与热更小窗，Windows/macOS 共用同一控制器；不弹出项目管理页或世界设置确认框。AI 始终显式使用 --non-interactive run --no-gui --detach --json。--no-gui、--detach、--json 和非交互输入均抑制调试小窗；不隐藏游戏。小窗关闭只隐藏视图，游戏结束会清理小窗。带小窗的前台运行 Ctrl+C 调用同一 stop 流程；Windows 保存保证仍以平台能力为准。远程始终用 detach。

## 统一运行时与玩家操作

游戏加载完成后执行 `runtime install --session <sid> --json`，一次注入 `mcpy.ui`、`mcpy.player` 和 `mcpy.api`。本地显式 `--local --project <项目>`，远程显式 `--remote <endpoint>`。bootstrap 可要求 `runtime-player`（调用端）和 `py`（执行端）。0.3.18 起不按引擎版本号限制，按实际 API 能力执行；接口错误中的 `engine / compatibility_hint` 提示可能的版本差异。以返回的 `player_capabilities` 为准，普通操作优先使用下表，无需重新查询原版 SDK。

这些 Python 方法通过同一会话的 `runtime py --side client` 调用；也有 `runtime player <动作>` CLI。先 `snapshot()` 读取位置、朝向、快捷栏、手持物品、饥饿值、箭数和瞄准目标。

| 目的 | 简写 |
|---|---|
| 观察玩家 | `mcpy.player.snapshot()` |
| 向前/侧向移动 | `mcpy.player.move(forward=1, right=0, duration_ms=500, sprint=False)` |
| 按角度看向 | `mcpy.player.look(pitch=0, yaw=90)` |
| 看向世界坐标 | `mcpy.player.look_at(x, y, z)` |
| 切换快捷栏 | `mcpy.player.select_slot(1)`，槽位统一为 **1–9** |
| 跳跃/限时潜行 | `mcpy.player.jump()` / `mcpy.player.sneak(duration_ms=500)` |
| 游戏内组合键 | `mcpy.player.key("CTRL+W", hold_ms=500)`，按当前游戏键位解释 |
| 攻击准星实体 | `mcpy.player.attack(snapshot=s["snapshot"])` |
| 挖掘准星方块 | `mcpy.player.dig(snapshot=s["snapshot"], duration_ms=1500)` |
| 使用手持物品 | `mcpy.player.use_item(snapshot=s["snapshot"], mode="auto", hold_ms=200)` |
| 吃手持食物 | `mcpy.player.eat(snapshot=s["snapshot"], hold_ms=2000)` |
| 普通弓蓄力射箭 | `mcpy.player.shoot(snapshot=s["snapshot"], hold_ms=1200)` |
| 批量连续动作 | `mcpy.player.sequence(steps)`，省略 `at_ms` 自动编排，支持 `delay_ms` 和 `wait` |
| 进度/停止自己的输入 | `mcpy.player.status(operation_id)` / `mcpy.player.stop()` |

`s` 必须来自当前玩家快照。攻击、挖掘和使用前会重新核对目标、槽位、手持物品和距离；界面打开时拒绝玩家动作。`right>0` 向右，`forward>0` 向前；它们是方向而不是速度。pitch 负值向上、正值向下；yaw 0 为南/+Z、90 为西/-X、-90 为东/+X。持续动作 20–10000ms，自动释放；发生移动不等于走到了指定坐标。

有已知连续步骤时优先一次提交队列，见 [玩家动作与连续计划](references/runtime-player.md) 的可直接使用示例；不要为了切换物品、等待、吃东西和射箭逐条消耗 Agent 往返。队列自动在每步重新观察，支持手持物品/目标断言，失败或界面变化后停止，不自动回滚已完成效果。未完成/结果未知时查 status，不重新提交。控制层没有桌面输入回退；弩和实体喂食/交易暂未适配，不能假装成功。

## 游戏内 UI：先读节点，再操作

涉及界面自动化时，先检查 `runtime ui --help`。统一 `runtime install` 已包含 UI；旧入口 `runtime ui install --session <id> --json` 也保留，重复安装同一版本不会重复监听。bootstrap 可要求调用端 `--require-capability runtime-ui` 和执行端 `--require-capability py`，不要仅凭工具版本推断支持。

按 [运行时 UI 操作](references/runtime-ui.md) 使用 `snapshot → 查看浅层语义树 → 单次节点动作 → snapshot`。树会合并重复标签、折叠布局容器，按区域与小组摆放相关控件；分组标题提供上下文，不能代替数字节点 ID 操作。优先采用游戏内节点操作；按返回的 `capabilities`、节点 `actions` 和实际引擎能力选择动作。每次刷新都会更换 snapshot，编号不可跨快照复用；布局或界面变化时重新观察，不猜路径和坐标。

`click` / `slide` 通过游戏内部触控事件触发正常交互，自动抬起，不发送桌面键鼠；`scroll` 直接操作滚动容器。`set-control-value` 仅写控件状态，不保证业务回调，不能用它的成功返回证明设置或交易已生效。操作后核对文字、值及实际目标状态；`pending` 查询 status，结果未知先找回动作，不重复点击。

节点信息不足时用 `screenshot --background-only` 补图。失败即停止截图，不回退抢焦点。需要桌面输入时明确判断用户是否允许游戏占用前台，再使用下面的键鼠流程；不要把私有引擎接口缺失默默转成前台输入。

## 桌面键鼠与验证脚本（需允许占用前台）

连续执行都先编排：省略 `at_ms` 时按前一步**计划结束**加本步 `delay_ms` 自动生成；指定 `at_ms` 也进入同一计划，不另设快速模式。详细例子及时间戳解释见 [连续动作编排](references/input-sequence.md)。Windows 序列返回部分失败记录，但没有持久化动作 status 或幂等重放；超时后先观察游戏，不能套用玩家队列的重查流程。

```bash
mcpy --remote <endpoint> screenshot --session <id> --output ./captures/before.png --json
mcpy --remote <endpoint> key --session <id> SHIFT+W --hold-ms 2000 --json
mcpy --remote <endpoint> mouse click --session <id> --x 400 --y 300 --width 1280 --height 720 --json
```

本机操作把 remote 改成 `--local --project "<Windows项目>"`。兼容脚本 [game_window.py](scripts/game_window.py) 的 `--remote/--local/--project/--command` 放在 screenshot/key/mouse 之前。
截图保存到调用端、不覆盖文件；查看 `image` 确认画面。绝对坐标对应截图客户区宽高，尺寸变化后重新截图。
键盘支持组合与 VK/SC/E0；鼠标支持点击、双击、滚轮、拖拽和 relative。相对位移不保证触屏模式转向，必要时在视角区域拖拽；均以截图验证效果。
世界准星已瞄准时，可用`mouse click-current --width <截图宽> --height <截图高> --button right`避免绝对鼠标移动带动视角。此操作仍核验会话、前台、画布大小、鼠标位于客户区且没有其他窗口遮挡；不是后台点击。组合点击先让修饰键状态同步，再发送鼠标按下，发送成功仍需检查游戏实际状态。
**F11** 切换鼠标／触屏模式，**F3** 循环调试层。切换后确认画面，测试结束恢复原状态，除非用户要求保留。
失焦、遮挡或释放失败时按[故障排查](references/troubleshooting.md)处理；不连续猜测输入。所有持有操作有时限并释放本次按键／按钮。
[smoke.py](scripts/smoke.py) 默认检查并打包；Windows/macOS 本地世界用 `--local --game`，远端用 `--remote <地址> --connect <服务器>`，均可显式加 `--mcs-auth`。
`--expect-log` 可重复；`--client-file` / `--server-file` 在世界就绪后执行一次 Python 2 验收脚本（服务端仅本地世界）。没有日志标记和脚本时只报告启动；默认等待期限 90 秒。脚本停止自己创建的会话，不用于需要保留游戏窗口的任务。
远程桌面交互由 Agent 查看下载的图，再调用远程键鼠；macOS Computer Use 不会自动看到 Windows。Windows 本机需占用前台的复杂操作可按需使用环境已有的 Computer Use，Qt 页和编辑器仍留给人工。

## 视频录制与逐帧分析

录制任务先检查执行端 `record` 和 `record-frames` 能力；bootstrap 可重复传入 `--require-capability`。新版 Skill 不代表旧 CLI 或旧原生组件支持录制。视频文件在 Windows 临时目录持续写入，下载到调用端；无需安装 FFmpeg。

```bash
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record start --session <sid> --duration 10 --fps 30 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive runtime player move --session <sid> --forward 1 --duration-ms 2000 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record status --session <sid> --recording <rid> --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record download --session <sid> --recording <rid> --output ./captures/clip.mp4 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record frames --session <sid> --recording <rid> --frame 0 --frame 30 --output ./captures/frames --json
```

示例中的玩家操作需先完成 `runtime install` 并确认 HUD 与玩家状态。保存 start 返回的 `recording` 作为 rid，保持同一 endpoint、project 和 session。start 在首帧写入后返回，随后可同时执行运行时动作；查询至 `completed` 再下载／提帧。返回 `video/images/manifest` 是调用端路径。Windows 本机将全局路由替换为 `--local --project "<Windows项目>"`，其余参数相同。

时长为整数 1–300 秒，帧率为整数 1–60 FPS，默认 10 秒／30 FPS，无音频。每个会话一次录制。固定视频帧可能重复源画面或跳过游戏呈现画面，不能据此保证完整捕获游戏每一帧；PNG 是编码后画面。检查清单中的 `frame/time/source_time/repeated`，查看下载的 PNG，再结合日志判断逻辑是否通过。

`time` 是视频内的秒数；`source_time` 是 Windows 单调时钟秒数，不是 Unix 时间，原始值保留在 `source_time_100ns`。高分辨率／高帧率可能超过机器编码能力，`encoder_too_slow` 时降低帧率或使用较小游戏窗口，不通过隐藏丢帧将失败当作完成。

提帧 `--frame` 从 0 开始，可重复，单次最多 100 个；也可改用重复的 `--at <秒>`，取 `floor(秒 × fps)`，两者互斥。输出目录及 MP4 路径必须不存在。需要连续分析时分批选择帧，避免一次提供全部图片。

提前结束使用 `record stop`，不停止游戏；游戏结束也会结束录像。短片若成功封装仍可下载，检查 `truncated/end_reason`。start 超时先用 `record status --session <sid> --list` 找回，不盲目重录；显式 `--request-id <32位小写hex>` 可找回同一请求。下载中断可重试到尚不存在的目标路径。

执行端产物完成后保留 24 小时，后续命令或服务启动清理过期文件；游戏退出后仍可下载。任务结束且文件已下载后可执行 `record delete --session <sid> --recording <rid>`，仅删除执行端产物。需要时读[远程录制与故障处理](references/remote-testing.md#视频录制)。

## 已启动会话的 Python 与热更

使用前检查本机或远端 `py` 能力，并确认 `status` 的会话仍在运行。游戏使用内置 Python 2；脚本文件在调用端按 UTF-8 读取，远程模式传输代码内容。

```bash
mcpy --local --project "<本机项目>" --non-interactive runtime py --session <id> --side client --code "1 + 1" --json
mcpy --remote <endpoint> --non-interactive runtime py --session <id> --file ./probe.py --json
```

本地世界可选 `--side server`，远程联机仅客户端。跨平台基线使用同步调用；仅在当前会话 `python.client_queue=true` 时使用 `--no-wait/--wait-until/py-result`，远程不支持这些队列选项，不能忽略等待条件直接执行。检查 `state`、`stdout`、`stderr`、`value` 和 `error`；`unknown` 表示请求可能已经在游戏中执行，先查日志与状态，不自动重试。脚本副作用由调用者负责，优先调用项目明确的测试函数。

热更支持 Windows/macOS 本地世界；手动目标必须属于当前项目的包，成功投递仍需观察游戏效果：

```powershell
mcpy --local --project "<本机项目>" runtime reload python --session <id> --module MyMod.client.logic --json
mcpy --local --project "<本机项目>" runtime reload python --session <id> --module MyMod.server.logic --side server --json
mcpy --local --project "<本机项目>" runtime reload ui --session <id> --json
mcpy --local --project "<本机项目>" runtime watch --session <id>
```

`runtime reload` 提供 `shader`、`material` 和 `particle` 入口，实际支持取决于后端和引擎；macOS 新运行包支持 JSON UI 定义重载（需重新创建自定义界面），旧运行包及当前 Material/Shader 返回 unsupported，已有粒子文件可热更，详见 [macOS 本地测试](references/macos-local.md)。引擎没有对应接口或已知会阻塞时返回 `unsupported`。3.9.0.401155／3.10.0.420447 的 Shader 已禁用；JSON UI 的 `triggered` 只表示重载请求已投递，须用画面确认效果。`runtime watch` 在成功组装文件后触发重载，停止监控不会停止游戏。不要对远程联机会话执行热更。

含服务端组件初始化的Python模块必须在服务端执行热更；服务端热更要求0.3.13+的CLI与新启动worker。工具在发送源码前检查worker声明的端侧能力，旧worker不支持时先正常保存并重启自己的会话。返回`reload_side_mismatch`表示执行端侧未确认，可能已有副作用，不自动重试。资源热更只能在客户端；watch 默认客户端，服务端模块须用 --side server，--side both 仅用于可安全重复执行的公共模块；不会自动重建现有类实例或事件订阅。首次runtime执行前先确认游戏加载完成；Safaia已连接不代表脚本系统已初始化。
