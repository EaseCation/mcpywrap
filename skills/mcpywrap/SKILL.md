---
name: mcpywrap
description: 使用 mcpywrap 管理《我的世界》中国版 Addon/地图项目与依赖，构建 ZIP，启动本地世界或尝试未认证服务器连接并读取日志；使用会话绑定的脚本截图和发送按键，复杂界面交互交接 Computer Use。
---

# mcpywrap

用公开 CLI 完成项目操作。无需通读仓库 docs、CLAUDE.md 或实现源码。

## 准备

- 项目操作使用绝对路径 `--project`，不依赖当前目录；临时 `connect` 无需项目。
- 检查 `mcpy --version`、`mcpy --help` 及要调用的子命令帮助。版本号不能代替能力检查。
- 需要安装时使用 [bootstrap.ps1](scripts/bootstrap.ps1)。脚本使用已有 uv，缺少时返回官方安装入口；默认复用已有可用安装，升级或更换来源使用 `-Upgrade`。
- 正式版本使用 `-Version`，固定源码使用 `-GitRef <完整提交 SHA>`，开发目录使用 `-EditablePath <绝对路径>`。当前 Skill 对应的 CLI 必须支持 `--project`、`--non-interactive`、`--json` 和会话命令。
- 从返回的 `command` 路径调用，不假定刚安装的工具已经进入当前 PATH。

## 命令工作流

命令采用 `mcpy --project <路径> --non-interactive <子命令> --json`。
读取退出码和 JSON 的 `ok/error/hint`，不要以终端出现“成功”字样作为唯一依据。

| 任务 | 子命令 |
|---|---|
| 新建或接入 Addon | `init --name demo --type addon` |
| 接入或创建地图 | `init --name demo --type map` |
| 添加包依赖 | `add "package-name>=1.0"` |
| 引用本地 Addon | `add --path ../common` |
| 移除本地引用 | `remove --path ../common` |
| 生成脚本模板 | `mod --name DemoMod` |
| 安装指定 SDK | `modsdk --version <版本>` |
| 构建到配置目录 | `build` |
| 生成分发 ZIP | `package` |
| 安装当前项目 | `sync --install` |

初始化不覆盖已有配置，也不隐式安装 SDK、依赖或打开模板窗口。
本地依赖应是包含行为包/资源包的 Addon 根目录，不需要先初始化被引用目录。
`package` 返回 `artifact`；检查文件确实存在。构建时主项目优先，本地路径不会自动变成可分发包依赖。
`dev` 持续输出文本日志，不使用 `--json`；修改依赖声明后重启监控。
`publish --yes` 是真实上传；只有用户请求发布时才调用。

## 本地世界验证

1. `doctor --json` 检查引擎与资源；编辑器缺失不等于无法运行游戏。
2. `run --no-gui --detach --json` 启动本次会话，只显示游戏本体。
3. 保存返回的会话 ID、PID、创建时间、程序路径及日志路径。
4. `status --session <id> --json` 查询状态；`logs --session <id> --tail 100 --json` 读取日志。
5. 使用项目约定的日志标记验证 Mod 加载。`running` 只表示进程存在。
6. 若用户要求一次性验证，结束后 `stop --session <id> --json`；用户要求保持游戏运行时保留会话并报告 ID。

可使用 [smoke.py](scripts/smoke.py) 自动检查并打包；`--game` 才运行游戏，
`--expect-log` 可重复指定加载标记。该脚本会停止自己创建的游戏；不要用于要求保留游戏窗口的任务。

## 网络连接（实验性）

网络能力需 CLI 0.3.3 或更高版本，先检查 `connect --help`。临时连接用 `mcpy connect <IP或主机名> --port 19132`，不读取项目配置。
固定目标在 `pyproject.toml` 添加以下表，再执行 `mcpy --project <绝对路径> --non-interactive run`：

```toml
[tool.mcpywrap.server]
host = "192.168.31.101"
port = 19132
```

纯连接目录只需此表，无需 `init`；Addon 项目仍校验依赖，但本版不装配本地 Mod。
不读取登录身份或 token，不能把进程创建成功当成进服成功。
在可持续运行的终端会话中执行，读取输出的 PID 和两路日志路径；Ctrl+C 结束本次游戏。
`--json` 在游戏退出后才返回最终结果；不支持 `--detach`、`--new`、世界实例 ID、Map 或 GUI。
网络运行不生成本地会话 ID，不使用 `status/logs/stop --session`、`smoke.py --game` 或 `game_window.py` 管理它。

## 游戏截图与键盘操作

固定截图和键盘输入优先使用 Skill 自带的 [game_window.py](scripts/game_window.py)，仅需 Windows 和 Python 标准库。
从已启动会话取得 ID；脚本通过公开 CLI 查询并再次校验 PID、创建时间、EXE 与窗口归属。

```powershell
python <skill目录>/scripts/game_window.py --project D:\mods\demo --session <id> --command <mcpy路径> screenshot --output D:\captures\before.png
python <skill目录>/scripts/game_window.py --project D:\mods\demo --session <id> --command <mcpy路径> key F11
python <skill目录>/scripts/game_window.py --project D:\mods\demo --session <id> --command <mcpy路径> screenshot --output D:\captures\after.png
```

脚本会激活游戏；截图仅含可见客户区，不含标题栏，不覆盖已有 PNG。
截图成功后用 Agent 的图片查看能力读取返回的 `image` 路径，不将路径存在等同于画面正确。
支持字母、数字、F1–F24、左右修饰键、导航键、小键盘、OEM 标点、IME 和媒体键；完整键名见 `key --help`。
用 `+` 或空格同时按住多个键：`key SHIFT+W --hold-ms 2000` 潜行前进，`key W A --hold-ms 1000` 斜向移动，
`key CTRL+W SPACE --hold-ms 500` 同时冲刺前进和跳跃（实际效果取决于游戏键位设置）。
默认持续 80 ms，允许 20–60000 ms；命名修饰键先按下，结束时逆序释放全部键，期间持续检查焦点。
其他键位可用 `VK:0xNN`（Windows 虚拟键）、`SC:0xNN`（物理扫描码）、`E0:0xNN`（扩展扫描码）；
扫描码不按字符解释，OEM 键含义随键盘布局变化。`NUMPAD_ENTER` 与普通 `ENTER` 分开处理。
按下失败、中断或失焦均尝试释放；不提供跨调用持续 key-down，避免脚本退出后角色一直移动。
`sent/released` 表示发送/释放结果，`effect_verified` 为 false；效果仍需截图或日志验证。

游戏中 **F11** 切换鼠标模式与触屏模式，便于验证不同输入模式的交互；
**F3** 循环切换多个调试专用信息层。每次切换后截图确认状态，不把“按一次”当成“设置到某模式”。
验证结束恢复原模式与信息层，除非用户要求保留。按键后有动画时，等画面稳定再截取结果。

目标窗口不唯一、失去焦点、修饰键按住、遮挡、屏幕外或全黑截图时会失败。
先按错误恢复条件再重试，不盲目连续输入；焦点在按下期间变化时，脚本会尝试释放键并报告失败。

## Computer Use：复杂游戏画面交互

涉及找按钮、坐标点击、拖拽、触屏布局验证时，按需读取环境已有的 Computer Use 技能。
使用会话的进程身份与当前画面定位目标；多个游戏窗口不得仅凭标题选择。
截图受当前显示环境限制无法完成时，也可交给 Computer Use；不要为绕过平台限制换底层实现。
Qt 管理、模板和日志页仅供人工使用，Agent 通过 CLI 完成相应操作；不自动操作编辑器界面。
发生错误时，仅按需阅读 [故障排查](references/troubleshooting.md)。
