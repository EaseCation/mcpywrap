---
name: mcpywrap
description: 使用 mcpywrap 管理《我的世界》中国版 Addon/地图与依赖，构建 ZIP，启动本地世界或网络服测试并读取日志；通过会话脚本截图和输入按键，复杂游戏交互交接 Computer Use。
---

# mcpywrap

用公开 CLI 完成项目操作。无需通读仓库 docs、CLAUDE.md 或实现源码。

## 准备

- 明确项目绝对路径，使用 `--project`；临时 `connect` 无需初始化项目，此路径仅用于保存会话，不读取项目配置。
- 检查 `mcpy --version`、`mcpy --help` 及所需子命令帮助。版本号不能代替能力检查。
- 安装使用 [bootstrap.ps1](scripts/bootstrap.ps1)，需要已有 uv；缺少时返回官方安装入口。默认复用已有安装，更换来源或升级需 `-Upgrade`。
- 正式版本用 `-Version`，固定源码用 `-GitRef <完整 SHA>`，开发目录用 `-EditablePath <绝对路径>`。始终使用返回的 `command`，不假设 PATH 已更新。
- bootstrap 返回实际 `capabilities`。任务需要时用 `-RequireCapability network-sessions` 或 `-RequireCapability mcs-auth`；缺少可选能力不影响普通构建。
- `mcs_auth.supported` 仅表示参数存在；`component_available` 为 true 才表示组件文件具备，null 表示旧 CLI 无法检查。它们都不证明已登录或系统策略允许启用。
- Git／可编辑安装可能不含 CI 生成的桥接组件；需要身份时优先使用正式发布包。不要因缺少组件自动编译、安装证书或读取凭据，按任务需要查阅[故障排查](references/troubleshooting.md)。

## 项目操作

有限命令采用 `mcpy --project <路径> --non-interactive <子命令> --json`。
读取退出码和 JSON 的 `ok/error/hint`，不要仅凭终端“成功”字样判定完成。

| 任务 | 子命令 |
|---|---|
| 新建或接入项目 | `init --name demo --type addon` 或 `--type map` |
| 添加／移除包依赖 | `add "package-name>=1.0"` / `remove package-name` |
| 引用／移除本地 Addon | `add --path ../common` / `remove --path ../common` |
| 生成脚本模板 | `mod --name DemoMod` |
| 安装指定 SDK | `modsdk --version <版本>`；`--list` 查询，`--latest` 显式选择最新 |
| 构建／分发 ZIP | `build` / `package` |
| 同步／安装当前项目 | `sync` / `sync --install` |
| 为用户打开编辑器 | `edit --detach`；返回进程信息，不代表界面任务完成 |

初始化不覆盖已有配置，不隐式安装 SDK、依赖或打开模板窗口。
本地依赖是包含行为包／资源包的 Addon 根目录，无需先初始化；本地路径不会自动变成可分发包依赖。
构建时主项目优先；`package` 返回 `artifact`，需确认文件存在。地图默认保留独立包，需要合并依赖资源时用 `package --merge`。
`dev` 持续输出文本日志，不用 `--json`；修改依赖声明后重启监控。
`publish --yes` 是真实上传，仅在用户请求发布时调用。删除实例和卸载包也需对应明确选项。

## 启动与验证游戏

选择目标后，统一使用后台会话进行日志、截图与输入操作：

| 目标 | 启动方式（补上全局 `--project <路径> --non-interactive`） |
|---|---|
| 本地世界 | `run --no-gui --detach --json` |
| 临时服务器 | `connect <IP或主机名> --port 19132 --detach --json` |
| 项目配置的服务器 | `run --detach --json` |

本地启动前用 `doctor --json` 检查引擎与资源；编辑器缺失不等于游戏无法运行。
临时 `connect` 自行预检，不读取项目的引擎配置；需要覆盖引擎时使用其 CLI 参数或环境变量。
固定服务器在 `pyproject.toml` 添加 `[tool.mcpywrap.server]`，填写 `host` 和可选的 `port`（默认 19132）。纯连接目录只需此表，无需 `init`。
网络模式仍不支持 Map、`--new`、世界实例 ID 或 Qt GUI；Addon 依赖会校验，但不装配本地 Mod。
旧 CLI 的 `connect --help` 没有 `--detach` 时，不能套用会话流程；先显式升级到具备该能力的版本或源码。

1. 保存启动结果的 `project`、`session`、PID、创建时间、程序路径与两路日志路径。
2. 始终用返回的项目路径：`status --session <id> --json`、`logs --session <id> --tail 100 --json`。
3. `running` 只证明进程存在；本地 Mod 加载、网络进服分别用约定日志标记或实际游戏画面确认。取得身份也不等于服务器接受连接。
4. 一次性验证结束后 `stop --session <id> --json`；用户要求保留游戏时报告会话 ID，不停止。

网络与本地会话均可使用下方窗口脚本。会话记录在返回项目的 `.runtime/sessions/<id>/`，与世界实例分开。
需要前台看日志时不加 `--detach --json`；网络前台 Ctrl+C 会停止本次游戏，本地前台中断则保留会话。

## 可选 MCS 身份与自动验证

仅在用户要求使用已登录身份时，给 `run` 或 `connect` 增加 `--mcs-auth`；默认匿名，失败不静默回退。
`doctor --mcs-auth --json` 只检查组件，不读取身份、不写缓存、不安装证书。
Agent 始终保持 `--non-interactive`；后台启动同时用 `--detach --json`。`studio_unavailable` 时提示用户打开并登录 MC Studio；其他错误按 `code/error/hint` 处理，不反复重试或改变系统保护。

[smoke.py](scripts/smoke.py) 默认检查并打包；仅在 `--game` 或 `--connect HOST` 时启动游戏：

```powershell
python <skill目录>/scripts/smoke.py --project D:\mods\demo --command <mcpy路径> --game --mcs-auth --expect-log "客户端已加载"
python <skill目录>/scripts/smoke.py --project D:\tests\server --command <mcpy路径> --connect example.com --port 19132 --expect-log "约定的进服标记"
```

`--game` 创建新的本地世界；`--connect` 不打包、不读取项目配置。两者均可显式加 `--mcs-auth`。
`--expect-log` 可重复，默认等待 90 秒；未指定标记时只报告启动状态。脚本收集日志并停止自己创建的会话，不用于需要保留游戏窗口的任务。

## 游戏截图、输入与 Computer Use

固定截图、按键和移动优先用 [game_window.py](scripts/game_window.py)，仅需 Windows 和 Python 标准库。
脚本通过 `status` 与窗口归属复核 PID、创建时间和 EXE，不接受任意 PID；本地与网络调用方式相同。

```powershell
python <skill目录>/scripts/game_window.py --project <返回的project> --session <id> --command <mcpy路径> screenshot --output D:\captures\before.png
python <skill目录>/scripts/game_window.py --project <返回的project> --session <id> --command <mcpy路径> key SHIFT+W --hold-ms 2000
```

截图是可见客户区 PNG，不覆盖已有文件；用图片查看能力读取返回的 `image`，不能只检查路径存在。
按键支持组合、20–60000 ms 长按及 VK/SC/E0 代码；完整键名见 `key --help`，特殊键与捕获限制按需看[故障排查](references/troubleshooting.md)。
`sent/released` 不证明游戏响应，需截图或日志确认；失焦或失败时会尝试释放全部键，不盲目重复输入。
**F11** 切换鼠标／触屏模式，**F3** 循环调试信息层；每次切换后截图确认，验证结束恢复原状态，除非用户要求保留。
复杂按钮查找、点击、拖拽或触屏布局验证，按需读取环境已有 Computer Use 技能，确认窗口后操作并验证结果。
用进程身份与当前画面共同定位，不仅凭 Minecraft 标题选窗口；截图受平台限制时也可交给 Computer Use，不绕过限制。
Qt 管理、模板与日志页仅供人工使用；Agent 使用 CLI，不自动操作编辑器界面。Computer Use 不可用时明确未完成的界面步骤。
