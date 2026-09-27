# mcpywrap

**用 Python 标准项目与依赖管理方式开发《我的世界》中国版 Mod 和资源包。**

[![PyPI Version](https://img.shields.io/pypi/v/mcpywrap)](https://pypi.org/project/mcpywrap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

mcpywrap 使用 `pyproject.toml` 管理项目，支持安装 Python 包依赖，也支持直接引用本地 Addon 目录。它将依赖管理、资源构建、游戏运行和 MC Studio 编辑器串成一套开发流程，方便多个项目共享代码与资源。

## 安装

需要 Python 3.9 或更高版本。游戏和编辑器启动功能需要 Windows、MC Studio 及已下载的游戏引擎。

推荐通过 [uv](https://docs.astral.sh/uv/) 安装：

```powershell
uv tool install mcpywrap
```

也可以使用 `pip install mcpywrap`。安装完成后，运行 `mcpy --help` 查看命令。

## 开始使用

进入你的 Addon 或地图项目目录，按向导初始化：

```powershell
mcpy init
```

之后可以直接运行游戏测试，或在 MC Studio 编辑器中打开项目：

```powershell
mcpy run
mcpy edit
```

需要查看项目和管理依赖时，运行 `mcpy ui` 打开图形界面。

## 复用代码和资源

对于已发布的 Python 包，使用包名添加依赖：

```powershell
mcpy add "package-name>=1.0"
```

对于本机已有的 Addon，直接引用它的目录：

```powershell
mcpy add --path "../shared-addon"
```

本地 Addon 无需先初始化或安装，可以直接使用 MCS 导出的目录。请选择包含行为包或资源包的 Addon 根目录；相对路径以当前项目目录为基准。

移除依赖使用 `mcpy remove <包名>` 或 `mcpy remove --path <目录>`。移除本地引用不会删除源目录。不带参数运行 `mcpy add` / `mcpy remove` 可进入选择向导。

本地路径适合同机开发；与他人共享项目时，需要同步这些目录，或将可复用组件发布为 Python 包。目录结构、配置及构建规则见[本地依赖参考](https://github.com/EaseCation/mcpywrap/blob/main/docs/local-dependencies.md)。

## 构建与日常开发

| 命令 | 用途 |
|---|---|
| `mcpy build` | 将项目和依赖构建到配置的输出目录 |
| `mcpy package` | 构建项目和依赖，在 `dist` 中生成可分发 ZIP |
| `mcpy dev` | 监控 Addon 源码与依赖变化，持续更新构建结果 |
| `mcpy mod` | 通过向导创建 Python Mod 框架 |
| `mcpy modsdk` | 管理网易 ModSDK |
| `mcpy run -n` | 创建新的游戏测试实例 |
| `mcpy run -l` | 查看已有实例 |
| `mcpy run -d <ID前缀>` | 删除指定实例 |

本地世界模式下，`mcpy run` 默认复用最近创建的实例。构建时主项目内容优先于依赖；修改依赖声明后，请重新启动 `mcpy dev`。

### 打包分发

在项目根目录执行 `mcpy package`，会先构建项目及 Python 包／本地 Addon 依赖，再生成 `dist/<项目名>-<版本>.zip`。名称和版本读取 `pyproject.toml` 的 `[project]`；不需要配置 `target_dir`。

Addon ZIP 内为 `<项目名>_bp/`、`<项目名>_rp/`（仅包含实际构建出的包）；地图 ZIP 根目录直接包含存档数据、行为包、资源包及世界包配置。地图默认保留独立包，使用 `mcpy package --merge`（或 `-m`）按构建规则合并依赖资源。构建产物中的空目录会保留。

重复打包成功后会替换同名 ZIP；失败时保留已有 ZIP，临时文件自动清理。

## 游戏启动与排查

通常不需要手动指定游戏路径。mcpywrap 会优先查找 MC Studio 登记的安装，必要时搜索固定磁盘中的标准下载目录，并跳过不完整的引擎版本。

遇到找不到游戏或缺少资源的提示，先运行：

```powershell
mcpy doctor
```

需要使用特定版本时，可以临时指定：

```powershell
mcpy run --engine-version 3.10.0.420447
```

已有实例默认保留原引擎版本；显式指定版本可以切换。自定义路径、项目级设置和环境变量的用法见[引擎配置参考](https://github.com/EaseCation/mcpywrap/blob/main/docs/engine-discovery.md)。

### 连接服务器（实验性）

临时连接无需项目配置，地址可以是 IP 或主机名，端口默认 `19132`：

```powershell
mcpy connect 192.168.31.101 --port 19132
```

固定目标可写入 `pyproject.toml`，随后在该目录执行 `mcpy run`：

```toml
[tool.mcpywrap.server]
host = "192.168.31.101"
port = 19132
```

空目录只需上述配置，无需执行 `mcpy init`；已有 Addon 项目也可添加此表。当前使用未认证连接，不读取登录身份或 token，不保证服务器允许进服；项目依赖仍会校验，但暂不装配本地 Mod。

网络模式前台输出日志并显示日志文件路径，按 Ctrl+C 结束本次游戏。暂不支持 Map 项目、GUI、`--detach`、`--new` 或本地世界实例 ID。

## AI Agent 使用

仓库提供标准 [mcpywrap Skill](https://github.com/EaseCation/mcpywrap/tree/main/skills/mcpywrap)，帮助 Agent 安装工具、管理依赖、
构建打包、启动游戏和检查日志，并通过自带脚本截图、发送组合键与模拟移动。

**安装 Skill**：可对支持 Skill 安装的 Agent 说：

> 请安装 GitHub 仓库 EaseCation/mcpywrap 中 skills/mcpywrap 目录下的 Skill。

也可以下载仓库 ZIP，将完整的 `skills/mcpywrap` 文件夹复制到对应 Agent 的技能目录。
无需从源码安装 Python 项目；CLI 和 Skill 分别安装，`pip/uv install` 不会自动注册 Skill。
Skill 中的 `scripts/bootstrap.ps1` 可使用已有 uv 安装 CLI，并检查是否具备所需命令能力。
请使用 mcpywrap 0.3.3 或更高版本；需要固定组合时，可从 `v0.3.3` 标签安装对应 Skill。

安装后可直接描述任务：

- “使用 mcpywrap 为这个 Addon 添加本地依赖，并生成分发 ZIP。”
- “启动这个项目，不弹日志界面，检查客户端和服务端的加载日志。”
- “启动游戏并截图，模拟组合按键移动，检查 F11 输入模式和 F3 调试信息层。”

Agent 通过 CLI 管理项目，Skill 自带游戏截图与键盘输入脚本；复杂游戏交互交给 Computer Use。Qt 管理与模板界面用于人工操作。
常用入口：`mcpy --project <目录> --non-interactive <命令> --json`。

## 更多信息

- 运行 `mcpy <命令> --help` 查看该命令的选项。
- [更新记录](https://github.com/EaseCation/mcpywrap/blob/main/CHANGELOG.md)
- [开发与验证](https://github.com/EaseCation/mcpywrap/blob/main/docs/development.md) · [发布流程](https://github.com/EaseCation/mcpywrap/blob/main/docs/releasing.md)
- 欢迎通过 [Issues](https://github.com/EaseCation/mcpywrap/issues) 反馈问题或提交 PR。

[MIT License](LICENSE) © EaseCation
