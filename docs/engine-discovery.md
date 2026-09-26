# 游戏引擎发现与诊断

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
