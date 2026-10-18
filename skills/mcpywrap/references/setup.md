# 安装、能力检查与执行路由

用于首次接入、缺少命令、升级或切换机器。已经确认命令和目标后，直接读对应操作页，不必每次运行 bootstrap。

## 找到可用 CLI

```text
uv run --no-project --python 3.12 "<skill>/scripts/bootstrap.py"
```

Windows 也可运行 `scripts/bootstrap.ps1`；PowerShell 调用带空格的可执行路径用 `& "<路径>"`。bootstrap 返回的 command 属于本机，后续使用它，不把游戏 EXE 当 CLI。默认复用安装；明确更换来源时加 `--upgrade`，并选择 `--version`、`--git-ref <可获取的完整SHA>` 或 `--editable-path <本机源码目录>`。本地未推送改动只能用本机源码安装，不能当远程 SHA 安装。

Skill 文件夹、CLI、正在运行的 worker、macOS 原生运行包分别更新。复制完整 Skill 后仍要核对实际命令；候选功能未发布时用包含该功能的源码或构建，不假定 PyPI 已具备。

| 当前需要的能力 | 检查方式 |
|---|---|
| 基础会话/项目命令 | bootstrap 返回基础能力；CLI `--help` |
| Git / QuMod | bootstrap `--require-capability git-dependencies` / `framework-presets` |
| 宿主项目脚本 | bootstrap `--require-capability project-scripts`；`script --help` |
| 本地 macOS 世界 | bootstrap `--local --require-capability macos-local-worlds`，再 `engine doctor --json` |
| Windows 服务 | Windows bootstrap `--local --require-capability serve` |
| 远程游戏调试 | bootstrap `--remote <endpoint> --require-capability remote-client --require-capability network-sessions --require-capability py` |
| 游戏内统一输入 | 调用端 bootstrap `--require-capability unified-input`，目标会话 `runtime input capabilities` |
| 本机双客户端 | `run/connect --help` 的 --clients、`status --help` 的 --group；本地主客机还要 `local-dual-client-manual` |
| Windows 录制 | 执行端 doctor 的 record/record-frames 和 media |

`mcpy --local doctor --capabilities --json` 的 `capabilities` 描述后端能力，`local_capabilities` 可含仅本机的 project-scripts；bootstrap 的 `local_capabilities` 是辅助脚本汇总的本机能力。远端结果看 `remote.capabilities`。字段来自不同接口，不假定它们是同一份列表。能力存在不等于资源已安装、已登录或游戏已就绪。

只有启动后才有会话级能力：本地用 `runtime capabilities --session <sid>`；输入动作另用 `runtime input capabilities`。这些约束不能由宿主平台、版本号或 Skill 文本替代。

## 路由与路径

路由优先级：显式 `--local/--remote` → MCPY_REMOTE → 项目 `[tool.mcpywrap].remote_url`。远端失败不回退本机。bootstrap 的 --remote 只检测，不保存路由；Agent 的独立终端调用应每次明确带目标。

| 操作 | 实际执行位置 |
|---|---|
| init/add/remove/mod/modsdk/sync/build/package/dev/publish/script | 调用端；不会因为 remote 配置而上传项目 |
| 本地世界 run、实例管理、restart、runtime reload/watch | 本机；显式 --local。macOS 仅 Addon 世界 |
| 配置 server 的 run、connect、status/logs/stop、runtime py | 按游戏路由；远程只支持网络单会话 |
| runtime install/input、旧 ui/player | 调用端封装，作用于所选会话的游戏通道；原始 Windows 设备后端另查执行端能力 |
| screenshot/record、旧桌面输入 | Windows 本机或 Windows 服务；不操作 macOS 桌面代替远端 |
| ui | 本机人工 PySide6 项目页 |
| serve / edit | Windows 本机；edit 不支持远程 MCEditor |

`--project` 指调用端已存在的绝对目录，纯 connect 不需要 init。远端响应的 remote_project/executable/log_path 是 Windows 路径；读取日志用 logs，截图/录像下载返回的 image/video 路径才属于调用端。

## 按需准备资源

Windows 先 `mcpy --local doctor --json` 检查 MC Studio 引擎，缺失时由用户在 MC Studio 准备；登录任务还检查 `doctor --mcs-auth --json`。Git/源码安装可能缺少发布构建附带的原生组件，按实际诊断处理，不用旧版本替换新功能来“修复”。

macOS 首次 run 可自动准备资源；安装、版本固定和升级见 [macOS 平台](macos-local.md)。首次配置 Windows HTTP 服务才读 [远程执行端](remote-testing.md)。不要为了本机离线打包而安装游戏或启动服务。

## Windows 引擎发现与覆盖

用于 doctor 报缺少引擎/资源，或用户明确指定版本/路径。默认优先 MC Studio 登记安装，再搜索标准下载目录，跳过不完整版本；编辑器缺失不等于游戏不可运行。

```text
mcpy --local doctor --mcs-download-path <下载目录> --json
mcpy --local --project <项目> --non-interactive run --engine-version 3.10.0.420447 --no-gui --detach --json
```

需要直接指定 EXE 时用 --game-executable <路径>。完整版本必须真实存在，3.10 不是通配符；独立 EXE 仍需资源目录与用户数据。EXE 不在标准版本目录时还需明确 engine_version，该声明不验证二进制内部版本；不要同时指向两套不同的标准安装。

| tool.mcpywrap 项目字段 | 本机环境变量 |
|---|---|
| game_executable_path | MCPY_GAME_EXECUTABLE |
| mcs_download_path | MCPY_MCS_DOWNLOAD_PATH |
| engine_version | MCPY_ENGINE_VERSION |

覆盖优先级：CLI > 环境变量 > 项目配置；项目相对路径按项目根解析，CLI/env 相对路径按调用目录解析。团队通常只提交版本，本机路径放 env。macOS 的固定运行包/引擎绑定按[平台页](macos-local.md)，不能套用 Windows EXE 规则。远程这些路径由 Windows serve 配置，调用端不直接覆盖 EXE/下载目录。
