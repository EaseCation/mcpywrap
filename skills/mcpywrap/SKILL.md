---
name: mcpywrap
description: 使用 mcpywrap 管理《我的世界》中国版 Addon/地图、依赖、预处理与打包，启动本地世界或联机会话，进行双客户端联调、Python 热更、UI/玩家操作和 Windows 录制。适用于该工具的实际项目开发与验收；业务 API 仍需查目标版本 ModSDK。
---

# mcpywrap

本 Skill 目录是 AI 操作 mcpywrap 的用法来源。先按用户任务选下面的一篇参考；只在出现相应子任务时再沿链接读取，不通读所有参考，也不把仓库设计草案当作现行用法。实际安装是否支持某能力，用 CLI 帮助与能力查询核对；Skill 更新不会更新 CLI、worker 或原生运行包。

## 调用约定

- 使用公开 CLI。示例中的 `mcpy` 指本机已确认的可执行命令；需要安装、升级或不确定执行位置时才读[安装与路由](references/setup.md)。
- 全局参数在子命令前：`mcpy --local --project <已有绝对目录> --non-interactive <命令>`。远程操作明确换成 `--remote <Windows服务HTTP地址>`，失败不回退本机；项目目录仍属于调用端。
- 有限命令加 `--json`；检查退出码和 `ok/error/code/hint`。`dev`、`runtime watch`、`serve` 是持续命令，不加 JSON。脚本尾参置于 `--` 之后。
- AI 启动本地游戏用 `run --no-gui --detach --json`，不操作 Qt/TUI；游戏仍需要图形会话和 GPU。保存返回的 session/group、项目及远程 endpoint，后续不换目标。
- **业务代码禁止依赖 `mcpy.*`。** `mcpy.input/ui/player/api` 仅由 runtime install 临时注入调试会话，不是 ModSDK 或可分发依赖。宿主生成脚本用工具 Python 3，游戏代码仍受内置 Python/目标 ModSDK 约束。
- `running`、请求 `completed/triggered` 不等于玩法效果已验证。只结束自己创建或用户指定的会话；unknown 不盲目重发，busy 不清锁或杀无关进程。

## 按当前任务选择阅读入口

| 用户正在做什么 | 先读这一篇 | 何时才继续读其他页 |
|---|---|---|
| 安装 CLI、检查环境、分清本机/远端 | [安装与路由](references/setup.md) | macOS 资源问题转平台页；Windows HTTP 服务转远程页 |
| 新建项目、Mod/SDK、构建、打包、编辑器、PyPI 分发 | [项目工作流](references/project-workflow.md) | 涉及依赖或预处理时再读对应页 |
| 加 Python/本地/Git 依赖、QuMod、克隆恢复、升级回退 | [依赖与 QuMod](references/project-dependencies.md) | 无需先读启动或输入协议 |
| 配置/运行宿主脚本、构建前生成资源、解释 dev 行为 | [项目脚本](references/project-scripts.md) | 真要编写生成器再读其样例；不引入自动预处理 watch |
| 启动/重开/停止本地世界、代码未应用、部署占用 | [本地会话生命周期](references/local-development.md) | 世界参数转设置页；实际热更/执行 Python 转调试页 |
| 自定义种子、地形、难度、游戏规则 | [世界设置](references/instance-world-settings.md) | 这些是实例创建参数，不是项目配置 |
| 两名玩家、多世界、组查询/重试/停止/热更 | [双客户端联调](references/dual-clients.md) | 普通输入绑定选中的成员，再读输入页 |
| 连接外部服务器、可选 MCS 身份 | [网络会话](references/network-sessions.md) | 只有跨机执行才读 Windows 服务部署 |
| 配置/使用 Windows HTTP 远程服务 | [远程执行端](references/remote-testing.md) | 不支持远程世界实例、双客户端或资源部署 |
| 已有会话执行 Python、模块/资源热更、runtime watch | [运行时调试](references/runtime-debug.md) | 组操作转双客户端页；不必重读启动教程 |
| 移动/攻击/操作 UI、观察节点 | [统一输入](references/runtime-input.md) | 能力/参数按目标会话查询，不猜旧协议 |
| 截图、录制视频、下载、逐帧检查 | [画面采集](references/capture.md) | 需要操作玩家时才读输入协议 |
| macOS 安装/升级运行包、能力与引擎限制 | [macOS 平台](references/macos-local.md) | 不为普通运行每次重读安装细节 |
| 已有明确错误或结果未知 | [故障定位](references/troubleshooting.md) | 先按错误定位，再读相应操作页 |

## 当前工作方式的关键变化

- 世界保存进度，部署决定代码：`--new` 只创建世界；再次 run 若接管已有会话，不应用新代码，也不执行预处理。具体更新选择见本地生命周期页。
- 普通 build/dev 不写运行目录；运行资源由受控部署发布。同版多世界可以并行，有其他读者时不能单方面换版。
- 两名玩家使用组；输入/Python/截图选具体 session，组热更与停止选 group。本地 `waiting_for_join` 需要用户点击局域网卡片，不是启动失败。
- 宿主任务使用 `script`；`runtime py` 才是在游戏执行。钩子按构建/打包/实际本地启动触发，runtime watch 和客机重试不运行它们。
- 查询与 GUI 依赖刷新只读；关闭管理/调试窗口保留游戏。取消准备与停止已经启动的游戏是不同操作。

## 仅在继续旧脚本时阅读

新输入任务统一使用 `runtime input`。旧入口的参数不能混进新 steps 协议；兼容入口从常规帮助隐藏，但可直接查其 `--help`。

| 旧脚本使用的入口 | 专用参考 |
|---|---|
| key/mouse、旧组合键与写法 | [兼容输入](references/input-writing.md) |
| input-sequence | [旧编排](references/input-sequence.md) |
| runtime ui | [旧 UI](references/runtime-ui.md) |
| runtime player | [旧玩家队列](references/runtime-player.md) |
| runtime player timeline | [旧时间线](references/runtime-key-timeline.md) |
