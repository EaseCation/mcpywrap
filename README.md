# 🧰 mcpywrap 

**《我的世界》中国版 ModSDK 与资源包的全周期管理工具**

[![PyPI Version](https://img.shields.io/pypi/v/mcpywrap)](https://pypi.org/project/mcpywrap/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

mcpywrap 是基于 Python 生态的《我的世界》中国版 ModSDK/资源包全周期管理工具，支持依赖管理、语法转换和自动化构建，助力开发者实现高效协作与代码复用。

## 🌟 核心特性

- 🧩 **模块化开发** - 基于 Addons 维度的依赖管理（基于包管理和依赖的开发与测试流程）
- 🔄 **现代语法** - 支持 Python3 现代语法特性，提升开发体验
- 📦 **生态兼容** - 无缝对接 PyPI 生态，支持标准 `pyproject.toml` 配置
- 🚀 **智能构建** - 一键打包符合 MCStudio 规范的成品 Addons
- 🔥 **热重载开发** - 实时监控代码变更，支持 MCStudio 热更新

## 📖 为何选择此工具？

### 传统开发痛点
- 📜 **代码复用困难** - 通过 **文件拷贝** 导致版本管理混乱
- 🚧 **协作效率低下** - 多项目 **重复代码** 维护成本高
- ⚠️ **代码质量** - 缺乏现代开发工具和语法支持

### mcpywrap 解决方案
1. **标准化开发**  
通过 `pyproject.toml` 声明项目元数据和依赖关系，实现真正的模块化开发

2. **直接启动测试和编辑**  
- 直接通过 `mcpy run` 启动游戏实例，支持热重载和实时构建，提升开发效率
- 通过 `mcpy edit` 命令，使用 MC Studio Editor 编辑器进行编辑

3. **生态集成**  
依托 pip 包管理体系，支持依赖的版本锁定和自动解析


## 🚀 快速开始

### 前置要求
- Python ≥ 3.9（游戏与编辑器启动需要 Windows 和 MC Studio）
- pip ≥ 21.0

### 安装
```bash
pip install mcpywrap
```

### 初始化项目
```bash
# 首先进入项目目录
mcpy init
```
交互式创建项目结构，自动生成标准的 Mod 框架。

### 运行测试
```bash
mcpy run
```

## 🛠 工作流指南

### 依赖管理
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy`                 | 维护项目，将项目安装到系统 site-package 环境            |
| `mcpy add "package>=1.0"` | 安装并声明 Python 包依赖 |
| `mcpy add --path ../common` | 直接引用本地 Addon 目录 |
| `mcpy remove <package>`        | 移除依赖               |

### 完整命令参考

```bash
mcpy --help
```

#### 依赖管理
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy add "package>=1.0"` | 安装成功后保存 Python 包声明 |
| `mcpy add --path ../common` | 添加本地 Addon 目录，无需初始化或安装该目录 |
| `mcpy remove <package>`        | 从项目配置中删除依赖并可选择卸载 |
| `mcpy remove --path ../common` | 仅移除本地引用，保留源目录 |

### 本地目录依赖

主项目仍使用 `pyproject.toml` 管理项目；引用的 Addon 可以是直接从 MCS 导出的目录，**无需 `mcpy init`、无需 `pyproject.toml`，也无需 pip 安装**。

```toml
[project]
name = "my-addon"
version = "0.1.0"
dependencies = ["published-addon>=1.0"]

[tool.mcpywrap]
project_type = "addon"
target_dir = "./build"
local_dependencies = [
    "../shared-addon",
    "D:/Minecraft/common-resources",
]
```

有效目录至少包含一个行为包或资源包及其 `manifest.json` 或 `pack_manifest.json`，例如：

```text
shared-addon/
  behavior_pack/        # 也支持 behavior_pack_*、BehaviorPack*
    manifest.json
    sharedScript/
  resource_pack/        # 也支持 resource_pack_*、ResourcePack*
    manifest.json
```

第一版不支持把单独的行为包／资源包、地图根目录、普通源码目录作为本地依赖，也不支持同一 Addon 中多个同类型包。不必同时具备行为包和资源包。

相对路径相对于**声明它的项目目录**解析，与执行命令前的其他工作目录无关。目标目录存在 `[tool.mcpywrap]` 时，继续读取该项目的 Python 和本地依赖；否则视为叶节点。读取不会初始化、安装或修改目标目录。重复引用按真实路径去重（包含 Windows 大小写和目录链接）；循环引用会报告引用链。同名目录使用不同内部标识，避免链接覆盖。

```powershell
mcpy add --path "../共享 Addon"
mcpy add --path "D:/Minecraft/common-resources"
mcpy remove --path "../共享 Addon"

# 不带参数进入来源选择／直接依赖选择向导
mcpy add
mcpy remove
```

CLI 保留传入的相对或绝对写法，不根据包参数猜测路径。`--path` 不能与包参数同时使用；本地移除不接受 `--uninstall`。目录失效后仍可移除声明。非交互环境必须传入参数，否则返回非零退出码。`mcpy init` 的依赖收集也支持两种来源。

添加目录时会先验证结构和依赖图，无效或循环引用不会写入配置。其 Python 依赖未安装或版本不满足时，会显示警告及可复制的 `mcpy add "requirement"` 命令，允许保存本地引用，但**不会自动安装**。构建、运行、编辑器启动前会重新完整校验。Python 包仍通过当前工具环境的 pip 安装，安装失败不保存新增声明；环境标记为假的 requirement 不参与当前平台的依赖图，普通 Python 库也不会当成 Addon 加载。

### GUI 添加与移除

运行 `mcpy ui`，在“添加新依赖”选择“Python 包”或“本地目录”。包模式支持可编辑下拉框及补全，安装在后台执行，完成前禁用冲突操作；失败会保留输入并显示原因。

本地模式可输入路径或“浏览目录”，预览解析后的目录、包结构和将保存的路径。默认保存相对路径；跨盘保存绝对路径，也可勾选“保存为绝对路径”。**选择目录本身不保存，点击“添加依赖”才写入配置**。错误输入保留供修改。

依赖列表显示来源、声明和不可用状态，详细原因显示在提示中。移除本地依赖的确认框会说明仅移除引用，源目录保留。每次修改后刷新运行包集合，每次启动前重新校验；失效依赖可继续移除。配置更新只影响后续启动，不自动更改正在运行的游戏。

### 构建顺序与迁移

旧配置无需迁移，省略 `local_dependencies` 等同于空数组。只有本地依赖、没有 Python 包依赖的项目同样支持 `build/run/edit/dev`（地图项目仍不支持 `dev`）。本地引用只用于此工具，**不会自动成为可通过 pip 分发、安装或锁定的依赖**；分发时需自行安排资源和路径。

**行为变更：完整构建和增量构建现在都以主项目为最高优先级。** 顺序为子依赖先于引用者；同级先 Python 包列表、再本地列表，各列表按声明顺序处理，后处理者覆盖重复文件／合并键；主项目最后。共享子依赖只处理一次，采用稳定的依赖优先遍历。保留已有 JSON／语言文件合并规则及主项目 manifest。删除高优先级来源文件后，增量构建会恢复低优先级来源内容。

构建在清空输出前校验依赖及路径，拒绝输出覆盖源项目／源包或与依赖目录重叠。`dev` 监控主项目和解析到的所有依赖目录，修改依赖声明后需要重启监控。

`run/edit` 仍将依赖作为独立包链接／编辑器包路径传递，以上构建覆盖规则不代表游戏引擎自身的资源包加载优先级。Windows 优先使用符号链接，无符号链接权限时可使用目录 junction；复用已有同目标链接，保留其他项目链接，同名冲突明确报错。

### 开发验证

```powershell
python -m unittest discover -s tests -v
```

自动化测试使用临时目录、Click、Qt 离屏及安装／启动替身。本机多项目验收脚本另行执行真实 CLI、pip、watchdog，可加 `--game` 启动已安装的 MCS 引擎。请先关闭已有游戏，使用独立环境和一个尚不存在的输出目录：

```powershell
uv venv test/acceptance-venv
uv pip install --python test/acceptance-venv/Scripts/python.exe -e . pip
test/acceptance-venv/Scripts/python.exe tests/manual_integration.py --workspace test/my-acceptance --game
```

脚本保留测试项目、构建结果、CLI/pip 日志和 `report.json`；实际游戏验证检查各 Mod 的服务端／客户端加载标记及游戏生成的包 UUID 列表，并清理本次创建的全局链接。测试存档和 `.runtime` 配置保留供复查。游戏验收仅替换日志窗口为 TCP 文件收集器，真实引擎、目录链接和运行配置均使用产品实现。

#### 项目初始化与开发
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy init`                   | 交互式初始化项目，创建基础的包信息及配置 |
| `mcpy mod`                    | 向导式创建 Python Mod 基础框架 |
| `mcpy build`                  | 构建为 MCStudio 工程 |
| `mcpy dev`                    | 使用watch模式，实时构建与热重载 |
| `mcpy edit`                   | 使用 MC Studio Editor 编辑器进行编辑 |

#### ModSDK与游戏实例
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy modsdk`                 | 管理网易我的世界ModSDK |
| `mcpy run`                    | 游戏实例运行与管理 |

#### 发布项目
| 命令                          | 说明                  |
|-------------------------------|---------------------|
| `mcpy publish`                | 发布项目到 PyPI |

#### 游戏实例管理详解

```bash
# 启动最新游戏实例
mcpy run

# 创建新的游戏实例
mcpy run -n

# 列出所有可用的游戏实例
mcpy run -l

# 删除指定的游戏实例
mcpy run -d <实例ID前缀>
```

## 游戏引擎发现与诊断

`mcpy run` 和 `mcpy edit` 共用引擎发现机制，图形界面使用同样的项目配置和环境变量。
默认先读取当前用户 MC Studio 注册表的两个视图，选择该安装中最新的完整引擎。
注册表安装无法满足要求时，再检查各固定磁盘根目录的
`MCStudioDownload/game/MinecraftPE_Netease`，合并候选后按版本选择。
不会读取运行进程、访问网络盘或递归扫描全盘，也不会自动保存发现的机器路径。

只有版本目录名有效且包含 `Minecraft.Windows.exe` 普通文件的目录才会入选。
例如 `3.10` 高于 `3.9`；临时目录、备份目录及未下载完成的版本会被跳过。
同版本按绝对路径排序，结果稳定；每次操作重新发现，操作内复用同一个结果。

先运行只读诊断，无需初始化 Mod 项目：

```powershell
mcpy doctor
mcpy doctor --json
mcpy doctor --engine-version 3.10.0.420447
```

诊断会显示候选与选中路径、注册表或磁盘来源、跳过原因，以及运行、编辑器、
Safaia 分别缺少的资源。JSON 包含 `candidates`、`selected`、`diagnostics`、
`error`、`resources` 和 `ok`。游戏发现或运行资源检查失败返回退出码 1；
编辑器、Safaia 缺失单独报告，不影响仅运行游戏的就绪状态。

### 固定路径和版本

以下字段均可选，可加入 Mod 项目的 `pyproject.toml`：

```toml
[tool.mcpywrap]
game_executable_path = 'D:\MCStudioDownload\game\MinecraftPE_Netease\3.10.0.420447\Minecraft.Windows.exe'
mcs_download_path = 'D:\MCStudioDownload'
engine_version = '3.10.0.420447'
```

每个字段独立采用 **命令行 > 环境变量 > 项目配置** 的优先级。
团队项目通常只提交 `engine_version`，本机路径可放在环境变量中：

| 项目配置 | 环境变量 | 命令行选项 |
|---|---|---|
| `game_executable_path` | `MCPY_GAME_EXECUTABLE` | `--game-executable` |
| `mcs_download_path` | `MCPY_MCS_DOWNLOAD_PATH` | `--mcs-download-path` |
| `engine_version` | `MCPY_ENGINE_VERSION` | `--engine-version` |

```powershell
$env:MCPY_MCS_DOWNLOAD_PATH = 'D:\MCStudioDownload'
mcpy run --engine-version 3.10.0.420447
mcpy edit --mcs-download-path 'D:\MCStudioDownload'
```

三个选项均适用于 `run`、`edit` 和 `doctor`。项目中的相对路径以
`pyproject.toml` 所在目录为基准；命令行与环境变量中的相对路径以调用目录为基准。
不自动向上搜索项目。版本需要填写实际完整版本，`3.10` 不作为 `3.10.*` 通配符。

显式路径无效、版本不存在或路径之间冲突时会报错，不悄悄改用其他安装。
未指定版本时，已有运行实例保留原版本，新实例选择默认最新完整版本；
显式指定版本可以主动升级已有实例。找不到旧实例版本时，会列出当前可用版本。

### 非标准目录与资源要求

显式 EXE 位于标准目录时，会反推关联下载目录；若同时指定下载目录，二者必须一致。
EXE 父目录不是版本号时，必须另外配置 `engine_version`。这里的版本是声明或目录信息，
不是对二进制内部版本的验证。

独立 EXE 可被发现，但仍需通过 `mcs_download_path` 或有效注册表定位资源目录。
当前本地世界启动需要下载目录中的 `componentcache/support/steve/steve.png`，
以及 `%APPDATA%/MinecraftPE_Netease/games/com.netease` 用户数据目录。
编辑器另需下载目录中的 `MCX64Editor/MC_Editor.exe`、`EngineAssert` 和启动器安装目录中的
`data/inner_res`；Safaia 单独检查。缺少资源时按诊断提示补齐，本工具不自动下载这些资源。

此功能不包含指定 IP/端口的第三方网络服启动。

## 🤝 参与贡献
欢迎提交 Issue 和 PR！请先阅读 [贡献指南](CONTRIBUTING.md)。

## 开源协议
[MIT License](LICENSE) © 2025 EaseCation
