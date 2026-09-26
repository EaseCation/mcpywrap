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
| `mcpy dev` | 监控 Addon 源码与依赖变化，持续更新构建结果 |
| `mcpy mod` | 通过向导创建 Python Mod 框架 |
| `mcpy modsdk` | 管理网易 ModSDK |
| `mcpy run -n` | 创建新的游戏测试实例 |
| `mcpy run -l` | 查看已有实例 |
| `mcpy run -d <ID前缀>` | 删除指定实例 |

`mcpy run` 默认复用最近创建的实例。构建时主项目内容优先于依赖；修改依赖声明后，请重新启动 `mcpy dev`。

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

## 更多信息

- 运行 `mcpy <命令> --help` 查看该命令的选项。
- [更新记录](https://github.com/EaseCation/mcpywrap/blob/main/CHANGELOG.md)
- [开发与验证](https://github.com/EaseCation/mcpywrap/blob/main/docs/development.md) · [发布流程](https://github.com/EaseCation/mcpywrap/blob/main/docs/releasing.md)
- 欢迎通过 [Issues](https://github.com/EaseCation/mcpywrap/issues) 反馈问题或提交 PR。

[MIT License](LICENSE) © EaseCation
