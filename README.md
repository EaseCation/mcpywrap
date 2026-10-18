# mcpywrap

**用 Python 标准项目与依赖管理方式开发《我的世界》中国版 Mod 和资源包。**

[![PyPI Version](https://img.shields.io/pypi/v/mcpywrap)](https://pypi.org/project/mcpywrap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

mcpywrap 使用 `pyproject.toml` 管理开发侧依赖，复用本地 Addon 的代码与资源，并串联构建、游戏测试和 MC Studio 编辑器。Python 包管理用于开发环境，不是游戏内的包安装器。

## 安装

需要 Python 3.9 或更高版本。Windows 使用 MC Studio 引擎；Apple Silicon macOS 13.0+ 使用预构建启动器和开发者 APK，支持离线 Addon 世界。两端共用 PySide6 项目界面；MCEditor 仅支持 Windows。参见 [Qt6 开发界面](docs/qt6-development.md) 和 [GUI 依赖许可说明](THIRD_PARTY_NOTICES.md)。

推荐通过 [uv](https://docs.astral.sh/uv/) 安装：

```powershell
uv tool install mcpywrap
```

也可以使用 `pip install mcpywrap`。安装完成后，运行 `mcpy --help` 查看命令。

从 Windows 源码检出安装时，先安装 Visual Studio 的 x86/x64 C++ 构建工具，再运行 `python scripts/build_all_native.py` 一次编译全部原生组件，最后执行 `pip install -e .`。正式发布包由 CI 编译并附带原生组件，普通安装无需本机编译。

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

为 Addon 一键准备 QuMod：`mcpy add --qumod`。新脚本目录自动生成入口，已有业务代码保留；
QuMod 作为通用 Git 项目依赖的预设管理，不进入源码仓库。团队成员克隆后执行 `mcpy sync` 即可恢复框架。
CLI／GUI 向导、官方 GitHub／Gitee 来源和版本依据见 [依赖与 QuMod](skills/mcpywrap/references/project-dependencies.md)。
其他仓库使用 `mcpy add --git <URL>`；标准导出、递归依赖与共享缓存见 [项目依赖](skills/mcpywrap/references/project-dependencies.md)。

将 Python 包安装到 mcpy 所在的工具环境并记录声明：

```powershell
mcpy add "package-name>=1.0"
```

对于本机已有的 Addon，直接引用它的目录：

```powershell
mcpy add --path "../shared-addon"
```

本地 Addon 无需先初始化或安装，可以直接使用 MCS 导出的目录。请选择包含行为包或资源包的 Addon 根目录；相对路径以当前项目目录为基准。

移除依赖使用 `mcpy remove <包名>` 或 `mcpy remove --path <目录>`。移除本地引用不会删除源目录。不带参数运行 `mcpy add` / `mcpy remove` 可进入选择向导。

本地路径适合同机开发；共享项目时需同步这些目录。工具目前通过包的本地安装来源识别 Addon，普通 PyPI 包或 wheel 安装成功不代表能参与组装；未识别到 Addon 的包会标记为“仅开发环境”。目录结构、配置及构建规则见[本地依赖参考](skills/mcpywrap/references/project-dependencies.md)。

**游戏运行边界：** 测试和正式游戏都使用内置 Python，不读取 `dependencies`，也不继承工具环境的 `site-packages`。`add`、`sync --install` 和 ModSDK 安装均不向游戏安装模块。游戏所需代码与资源必须随 Addon 携带，或由用户加载相应 Mod；纯 Python 库也不会自动复制，仍需适配游戏解释器和 ModSDK。原生扩展及依赖外部安装步骤、系统环境的库不能直接用于游戏；包内 `.pyd/.dll/.so/.so.*（版本号）/.dylib` 会阻止构建和启动。

## 构建与日常开发

Git 项目使用 `[[tool.mcpywrap.git_dependencies]]` 声明，支持 Addon 与纯代码导出、递归子依赖及固定提交。
`mcpy sync` 获取并注册，运行与发布时组装；共享源码缓存不提交 Git。
现有 `code_libraries` 声明保持兼容，说明见[代码库依赖](docs/code-libraries.md)。

| 命令 | 用途 |
|---|---|
| `mcpy build` | 将项目和依赖构建到配置的输出目录 |
| `mcpy package` | 构建项目和依赖，在 `dist` 中生成可分发 ZIP |
| `mcpy dev` | 监控 Addon 源码与依赖变化，持续更新构建结果 |
| `mcpy mod` | 用参数或终端问答创建 Python Mod 框架 |
| `mcpy modsdk` | 管理网易 ModSDK |
| `mcpy run -n` | 创建新的游戏测试实例 |
| `mcpy run -l` | 查看已有实例 |
| `mcpy run -d <ID前缀>` | 删除指定实例 |

本地世界保留进度，重新运行使用当前项目代码；`--new` 只新建世界，接管已运行会话不应用新代码。普通 build/dev 输出与运行部署分开，同版多世界可共享部署，换版须遵守读者占用。当前操作规则统一见内置 Skill 的 [本地生命周期](skills/mcpywrap/references/local-development.md) 和 [项目工作流](skills/mcpywrap/references/project-workflow.md)。

构建、ZIP 打包与实际本地启动前可运行宿主脚本；配置和 dev/watch 边界统一见 [项目脚本](skills/mcpywrap/references/project-scripts.md)。

### 打包分发

游戏 ZIP 与 Python/PyPI 分发是不同操作。产物格式、地图合并、失败保留与验收要求见 [项目工作流](skills/mcpywrap/references/project-workflow.md#游戏-zip)。

## 游戏启动与排查

### 运行时 Python 与本地热更

用户用法统一维护在 [内置 Skill](skills/mcpywrap/SKILL.md)，按任务阅读，无需通读架构文档：

- 启动、实例、停止与共享部署：[本地生命周期](skills/mcpywrap/references/local-development.md)。
- 已有会话的 Python、资源重载、监控：[运行时调试](skills/mcpywrap/references/runtime-debug.md)。
- 两名玩家、成员选择、组更新与重试：[双客户端联调](skills/mcpywrap/references/dual-clients.md)。
- 资源发现与平台差异：[安装与路由](skills/mcpywrap/references/setup.md)、[macOS 平台](skills/mcpywrap/references/macos-local.md)。

### 网络连接与登录身份

外部服务器连接、可选 MCS 身份与进服判断见 [网络会话](skills/mcpywrap/references/network-sessions.md)。需要另一台 Windows 执行游戏时，再按 [远程执行端](skills/mcpywrap/references/remote-testing.md) 配置服务。远程连接不部署本地 Mod，也不提供世界实例管理。

## AI Agent 使用

安装仓库内完整的 [mcpywrap Skill](skills/mcpywrap/SKILL.md)。可让 Agent 安装 `EaseCation/mcpywrap` 的 `skills/mcpywrap` 目录，或将整个文件夹复制到其技能目录。CLI 与 Skill 分别安装，安装 Python 包不会自动注册 Skill。

Skill 按当前任务选择参考，不要求 AI 通读产品文档。可直接描述：

- “为这个 Addon 添加 QuMod，并生成分发 ZIP。”
- “运行前把策划表生成 JSON，检查游戏加载结果。”
- “保留原世界，用两个客户端验证同步，只重试失败的客机。”

日常输入使用 [统一输入协议](skills/mcpywrap/references/runtime-input.md)；截图、录制和逐帧检查见 [画面采集](skills/mcpywrap/references/capture.md)。跨机执行见 [Windows 远程服务](skills/mcpywrap/references/remote-testing.md)。`mcpy.*` 只供临时调试，不是游戏业务代码依赖。

## 更多信息

- 运行 `mcpy <命令> --help` 查看该命令的选项。
- [更新记录](https://github.com/EaseCation/mcpywrap/blob/main/CHANGELOG.md)
- [开发与验证](https://github.com/EaseCation/mcpywrap/blob/main/docs/development.md) · [发布流程](https://github.com/EaseCation/mcpywrap/blob/main/docs/releasing.md)
- 欢迎通过 [Issues](https://github.com/EaseCation/mcpywrap/issues) 反馈问题或提交 PR。

[MIT License](LICENSE) © EaseCation
