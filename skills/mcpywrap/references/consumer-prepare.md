# 使用依赖提供的资源准备

用于玩法项目依赖框架，由框架工具处理玩法自己的素材。框架工具与运行库来自同一个依赖版本；消费项目持有素材、业务配置和生成结果。编写框架入口时转[作者接入](consumer-prepare-author.md)，普通使用无需阅读作者协议。

## 接入与恢复

首次接入或不确定目标 CLI 能力时，确认 `mcpy --local doctor --capabilities --json` 的 `local_capabilities` 包含 `consumer-prepare`；bootstrap 可用 `--require-capability consumer-prepare`。Skill 更新不等于 CLI 已升级。

新依赖按[依赖页](project-dependencies.md)使用 `add --path` 或 `add --git`，保留指定来源与版本。已有依赖只需恢复，不重复 add。消费项目无需复制启动器、登记 provider ID 或添加三个 hooks。

```text
mcpy --local --project <项目绝对目录> --non-interactive sync --json
mcpy --local --project <项目绝对目录> --non-interactive package --json
```

两步之间按 add/sync 返回的 `preparation.consumer_prepare[].example` 或 diagnostics 填写业务配置。使用依赖作者实际给出的表名和字段，不把其他框架的配置当作通用格式。已配置好依赖和环境的项目直接 build/package/启动即可。

sync 仅恢复依赖和准备环境，不执行资源生成。它可能 `ok=true` 且 `preparation.ready=false`：环境可用但业务配置仍缺项，需要修配置，不必重建环境。独立打包、游戏启动和玩法效果分别验证。

## 工具环境

默认使用消费项目 `.venv`。sync 在环境不存在时，从本机已有 Python 中选择满足全部启用入口要求的版本创建；优先最高兼容版本，同版本按路径稳定选择。检查返回的 `environment.python/version/state`，新建时还有 `created_with`。

已有环境不兼容时停止，不自动删除或重建；缺少兼容 Python 时按错误安装对应版本后再 sync。不会下载解释器或安装框架所需第三方库；build/run 也不创建环境或回退到其他解释器。sync 失败时，`sources_synced=true` 表示依赖已经恢复，继续按 error/code/hint 修复准备问题。

若框架需要第三方库，使用 `environment.python` 指向的解释器执行 `-m pip install <作者要求的发行包>`。`mcpy add <包名>` 和 `sync --install` 操作的是 mcpy 工具环境，不能据此判断项目 `.venv` 已有该库。环境准备失败也不是修改游戏 Python 依赖的理由。

## 执行时机

| 操作 | 资源准备行为 |
| --- | --- |
| build / package | 根项目对应 before_* 任务先执行，再执行依赖准备；各一次，package 不连带执行 before_build |
| dev | 仅首次准备；原始素材后续修改需要重新构建并应用 |
| 本地 run、Qt 启动、restart | 真正准备新游戏进程时执行，在最终资源指纹和组装前 |
| 本地主客机组 | 主机一次；补齐或重试客机不执行 |
| 接管已有会话 | 不准备、不重新部署；应用素材修改需重启会话或 stop 后重新 run |
| runtime reload/watch、网络连接、远程 run | 不执行原始素材预处理 |
| add/sync/remove、查询、edit/publish | 不执行依赖入口；sync 可创建工具环境 |

package 后再 run 是两个操作，各执行一次。生成器可自行避免重复改写文件，但不能依赖上次输出替代失败的本次准备。当前能力适用于 Addon 根项目；普通依赖自己的 hooks 不会递归执行。

## 查询与诊断

```text
mcpy --local --project <项目绝对目录> --non-interactive script list --effective --json
```

`ok=true` 只表示查询成功，还要查看 `complete`、`ready` 和 `diagnostics`。`complete=false` 时任务可能尚未发现完整；`ready=false` 时按诊断修复。旧 `script list --json` 只返回根任务，不能用空的 scripts 列表判断没有依赖准备。

ready 仅反映当前启用任务的静态预检。还要确认预期来源确实为 enabled；disabled/not_transitive 不会因 ready=true 自动启用，查询也不会生成资源。

`consumer_prepare` 列出来源、配置示例和状态；`execution_order` 给出各事件的执行顺序。查询不会执行入口、恢复依赖、创建环境或日志；解释器版本通过有限只读探测取得。

| 现象 | 下一步 |
| --- | --- |
| Git 工具源码缓存缺失 | 显式 sync；若依赖本身未交付入口文件，修复依赖版本或交由作者处理 |
| prepare_environment_unavailable / prepare_python_unavailable | 查看 environment 的实际路径、版本要求与来源；修复环境或使用下述显式覆盖 |
| consumer_config_invalid | 按 issues 中的 TOML 路径及当前依赖示例修配置；schema 不会自动补默认值 |
| not_transitive | 该间接依赖没有导出传递准备；按项目实际依赖关系决定是否直接引用，或由框架作者开启传递，勿补写三份 hooks |
| disabled | 项目已显式停用此来源；按预期检查 prepare.disabled，停用不表示资源已更新 |
| script_config_changed | 本次配置、身份或工具源码发生变化；稳定输入后重试，不循环自动重发 |
| script_failed / script_timeout / script_cancelled | 查看 script_log 与业务诊断；后续组装/新启动已阻止，但源码写入不自动回滚 |

日志沿用 `.mcpy/scripts/<操作 ID>/`，任务记录含 `kind=consumer_prepare` 和来源。单独验证生成使用 build；`script run <name>` 仍只执行根命名任务。出现 script_recovery_required 时按[故障定位](troubleshooting.md)核对进程状态，不删记录抢锁。

## 需要时才使用的覆盖

已有外部环境可指定解释器路径，相对消费项目根或使用绝对路径：

```toml
[tool.mcpywrap.prepare]
python = ".tools/bin/python"
```

Windows 使用对应的 `Scripts/python.exe`。mcpy 验证此环境但不创建或修改它；根 scripts 的 python 默认仍使用 mcpy 自身解释器。

只使用运行库或自行维护生成物时，可显式停用来源：

```toml
[tool.mcpywrap.prepare]
disabled = [
    { path = "../local-framework" },
    { git = "https://example.org/team/framework.git", subdir = "." },
]
```

Git URL 与现有声明匹配，subdir 默认 `.`。选择器覆盖同一来源的别名、安装目标和传递路径，升级后仍停用；运行库依赖保留。不要为了掩盖缺配置或脚本失败自动添加停用项。

仅通过 `unbundled=true` 引用的依赖暂不支持 consumer_prepare，避免生成文件残留到发布包。`script list --effective` 查看运行准备计划；发布依赖用 `deps --bundled-only --json` 查看。

## 独立示例

需要可复制的演示时，将本 Skill 的 [assets/consumer-prepare](../assets/consumer-prepare/) 整体复制到新的工作目录，以其中的 game 为项目执行上述 sync/package。framework 提供工具与运行库，game/data/items.json 是原始数据；修改后再次构建可检查生成结果。不要直接在 Skill 资产目录运行会写文件的命令。
