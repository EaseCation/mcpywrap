---
name: mcpywrap
description: 使用 mcpywrap 管理《我的世界》中国版 Addon/地图、依赖、项目脚本与依赖自带的资源准备，完成构建打包、本地或网络会话、双客户端联调、Python 热更、UI/玩家操作及画面采集。适用于该工具的实际项目开发与验收；业务 API 仍需查目标版本 ModSDK。
---

# mcpywrap

本 Skill 目录是 AI 操作 mcpywrap 的用法来源。先按用户任务选下面的一篇参考；只在出现相应子任务时再沿链接读取，不通读所有参考，也不把仓库设计草案当作现行用法。实际安装是否支持某能力，用 CLI 帮助与能力查询核对；Skill 更新不会更新 CLI、worker 或原生运行包。

## 调用约定

- 使用公开 CLI。示例中的 `mcpy` 指本机已确认的可执行命令；需要安装、升级或不确定执行位置时才读[安装与路由](references/setup.md)。
- 全局参数在子命令前；桌面本地示例：`mcpy --local --project <已有绝对目录> --non-interactive <命令>`。远程操作明确换成 `--remote <Windows服务HTTP地址>`，失败不回退本机；项目目录仍属于调用端。
- 有限命令加 `--json`；检查退出码和 `ok/error/code/hint`。`dev`、`runtime watch`、`serve` 是持续命令，不加 JSON。脚本尾参置于 `--` 之后。
- AI 启动本地游戏用 `run --no-gui --detach --json`，默认请求不聚焦的后台窗口，不操作 Qt/TUI；游戏仍需要图形会话和 GPU。macOS 旧包缺少后台协议时需升级运行包，不擅自改用 `--foreground`。保存返回的 session/group、项目及远程 endpoint，后续不换目标。
- mcpy 负责工程、会话和诊断取证，不解释 ModSDK 业务规则，也不根据日志推断模组健康；API/事件/UI 语义查对应版本的 ModSDK 文档，可使用独立文档 MCP。
- **业务代码禁止依赖 `mcpy.*`。** `mcpy.input/ui/player/api` 仅由 runtime install 临时注入调试会话，不是 ModSDK 或可分发依赖。宿主生成脚本用工具 Python 3，游戏代码仍受内置 Python/目标 ModSDK 约束。
- `running`、请求 `completed/triggered` 不等于玩法效果已验证。只结束自己创建或用户指定的会话；unknown 不盲目重发，busy 不清锁或杀无关进程。

## 按当前任务选择阅读入口

| 用户正在做什么 | 先读这一篇 | 何时才继续读其他页 |
|---|---|---|
| 安装 CLI、检查环境、分清本机/远端 | [安装与路由](references/setup.md) | macOS 资源问题转平台页；Windows HTTP 服务转远程页 |
| 新建项目、Mod/SDK、构建、打包、编辑器、PyPI 分发 | [项目工作流](references/project-workflow.md) | 涉及依赖或预处理时再读对应页 |
| 加 Python/本地/Git 依赖、QuMod、克隆恢复、升级回退 | [依赖与 QuMod](references/project-dependencies.md) | 无需先读启动或输入协议 |
| 当前项目自己的脚本、手动任务和根 hooks | [项目脚本](references/project-scripts.md) | 要编写生成器时再读其样例 |
| 使用框架处理本项目素材、准备环境或排错 | [消费者准备](references/consumer-prepare.md) | 添加或恢复依赖转依赖页；应用到游戏转本地生命周期页 |
| 框架作者导出消费者入口、配置协议及示例 | [作者接入](references/consumer-prepare-author.md) | 消费者操作沿链接读取；可复制模板随 Skill 提供 |
| 启动/重开/停止本地世界、代码未应用、部署占用 | [本地会话生命周期](references/local-development.md) | 世界参数转设置页；实际热更/执行 Python 转调试页 |
| 自定义种子、地形、难度、游戏规则 | [世界设置](references/instance-world-settings.md) | 这些是实例创建参数，不是项目配置 |
| 两名玩家、多世界、组查询/重试/停止/热更 | [双客户端联调](references/dual-clients.md) | 普通输入绑定选中的成员，再读输入页 |
| 连接外部服务器、可选 MCS 身份 | [网络会话](references/network-sessions.md) | 只有跨机执行才读 Windows 服务部署 |
| 配置/使用 Windows HTTP 远程服务 | [远程执行端](references/remote-testing.md) | 不支持远程世界实例、双客户端或资源部署 |
| 已配对 Android 宿主或明确准备手机开发环境 | [本机 App 接入](references/application-host.md) | 普通桌面项目无需阅读；绑定工作区按宿主能力执行 |
| 已有会话执行 Python、模块/资源热更、runtime watch | [运行时调试](references/runtime-debug.md) | 组操作转双客户端页；不必重读启动教程 |
| 移动/攻击/操作 UI、观察节点 | [统一输入](references/runtime-input.md) | 能力/参数按目标会话查询，不猜旧协议 |
| 截图、录制视频、下载、逐帧检查 | [画面采集](references/capture.md) | 需要操作玩家时才读输入协议 |
| macOS 安装/升级运行包、能力与引擎限制 | [macOS 平台](references/macos-local.md) | 不为普通运行每次重读安装细节 |
| 已有明确错误或结果未知 | [故障定位](references/troubleshooting.md) | 先按错误定位，再读相应操作页 |

## 当前工作方式的关键变化

- 世界保存进度，部署决定代码：`--new` 只创建世界；再次 run 若接管已有会话，不应用新代码，也不执行预处理。具体更新选择见本地生命周期页。
- 普通 build/dev 不写运行目录；运行资源由受控部署发布。同版多世界可以并行，有其他读者时不能单方面换版。
- 两名玩家使用组；输入/Python/截图选具体 session，组热更与停止选 group。Windows 新版默认自动加入，`joining` 等待 worker 完成；手动模式的 `waiting_for_join` 需要点击局域网卡片。
- 项目自己的宿主任务用 scripts/hooks；依赖提供的资源处理用 consumer_prepare；`runtime py` 在游戏内执行。有效准备计划使用 `script list --effective --json`，还需检查 complete/ready，不能只看查询的 ok。
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
