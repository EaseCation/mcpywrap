# 项目脚本与前置处理

项目可以在 `pyproject.toml` 中定义有限时的宿主机脚本，并在构建、游戏 ZIP 打包或本地世界启动前执行。任务运行于工具所在电脑，不在游戏 Python 环境，也不会传到远程 Windows 服务端执行。

使用前检查 `mcpy script --help`。`mcpy --local doctor --capabilities --json` 的 `local_capabilities` 包含 `project-scripts` 时支持本功能；bootstrap 也支持 `--require-capability project-scripts`。不能只凭 CLI 版本号判断具备此能力；旧 CLI 可能忽略新配置。

## 配置

```toml
[tool.mcpywrap.scripts.assets]
python = "tools/assets.py"
args = ["--quality", "development"]
env = { ASSET_MODE = "development" }
timeout = 120

[tool.mcpywrap.scripts.check]
cmd = ["node", "tools/check.mjs"]
timeout = 30

[tool.mcpywrap.hooks]
before_build = ["assets"]
before_package = ["assets", "check"]
before_run = ["assets"]
```

`python` 与 `cmd` 二选一：

- `python` 是项目根目录内的相对脚本路径，使用 mcpy 自己的 Python 解释器，`args` 为固定参数数组。uv tool 安装的 mcpy 使用工具隔离环境，不自动读取项目 `.venv`。需要 Pillow 等库时，先在选定工具环境准备好依赖，或用 cmd 明确调用其他已经准备好的环境。
- `cmd` 是完整 argv 数组，包括程序名和参数。程序名从继承的 PATH 查找；带路径的程序相对项目根解析。不支持另加 args。
- cwd 始终为 `--project` 指向的项目根，不受调用终端所在目录影响，不修改 GUI 的全局工作目录。
- env 覆盖继承环境，键值必须是字符串，不能覆盖工具的 `MCPY_*` / `_MCPY_*` 字段。
- timeout 默认 120 秒，须为大于 0、不超过 86400 的有限秒数。每个任务分别计时，列表串行运行；失败、超时或取消立即中断后续任务和本次构建/启动。

不解释通配符、变量替换、`&&`、管道或重定向。复杂逻辑请写在 Python/Node 等程序里。Windows 的 `.cmd/.bat` 包装器不能直接作为 cmd 的程序；需要时显式调用 `cmd.exe /c` 或 PowerShell，并按所选 shell 的规则编写参数。GUI 启动时 PATH 可能与终端不同，缺少工具会明确报错，不会自动安装或切换 shell。

这是项目工具配置，与 `[project.scripts]` 的 Python 安装入口无关。只有当前根项目的任务会被自动执行，不递归执行本地/Git/Python 依赖中的 hooks。

## 手动执行

```text
mcpy --project <项目> script list --json
mcpy --project <项目> script run --json assets -- --quality release
```

`list` 只读，不执行任务或创建日志。`run` 只执行命名任务，不触发任何生命周期。`--` 后的参数原样追加到固定 argv，子脚本的 `--json` / `--help` 不改变父命令的输出模式；重复选项由子脚本解释。

脚本必须能独立完成，stdin 已关闭；不能等待输入、启动脱离管理的后台服务或把有限任务当常驻 watch。如需持续生成，直接在终端运行生成器自己的 `python tools/assets.py --watch`。

脚本内不应递归调用 mcpy 的构建、启动、依赖写操作；需要组合任务时在 Python 内显式调用处理函数或外部程序。只读查询可以使用。

## 自动执行时机

| 操作 | 执行 |
|---|---|
| build | before_build 一次，然后组装 |
| package | before_package 一次，然后组装并压缩；不额外运行 before_build |
| dev | 首次构建前 before_build 一次；后续文件事件不重复执行 |
| 本地 run、Qt 启动、单会话 restart | 真正准备新游戏进程时 before_run 一次，在部署指纹和资源组装前 |
| 本地主客机组 | 主机准备时一次；补齐或重试客机不执行 |
| 接管已运行世界、查询、GUI 依赖刷新 | 不执行 |
| runtime reload/watch | 不执行 |
| 网络 run/connect、远程 run | 不执行本地启动钩子，不装配或上传本地资源 |
| add/remove/sync、edit、publish | 不执行；publish 是 Python 包发布，不是游戏 ZIP 打包 |

Addon 与 Map 沿用原有平台支持范围。项目和包的骨架必须已存在；前置脚本用于生成包内内容，不用于修改 pyproject、依赖锁、manifest/包身份或世界配置。这些配置在执行期间变化会使本次操作失败。

同一事件按数组顺序运行，不自动推断前后缀。无变化的新启动仍执行 before_run，生成后的包内容相同则复用现有部署。接管已有游戏不会执行生成，因此 `source_matches` 只比较当前可组装的包文件，不保证原始表格、图片或生成器已经处理。

## 编写生成器

原始素材和宿主代码放在包外，只有业务输出放在包内。需要可复制的生成脚本时读 [CSV → JSON 示例](script-example.md)。

脚本可读取 `MCPY_PROJECT_ROOT`、`MCPY_EVENT`（manual 或具体 hook）、`MCPY_OPERATION`（script/build/package/run）。首版不提供输入图、产物挂载、任务缓存或目标引擎推断；需要固定引擎格式时由项目明确传入参数。

## 日志、取消与边界

每次任务的日志和结果位于 `.mcpy/scripts/<操作 ID>/output.log`、`result.json`。有限 CLI 的 JSON 包含脚本记录或 `script/script_log/script_exit_code` 等失败详情，stdout 保持一个 JSON 对象，任务输出送 stderr。运行准备在 worker 中执行，任务输出也可通过会话的 worker 日志查询；Qt 在准备阶段显示任务，并提供“取消准备”。

Ctrl+C、任务 timeout 或本次 session 的 stop 请求会取消任务并回收自己拥有的子进程。监督进程观察调用方退出；若无法确认进程已经结束，保留记录并报告 `script_recovery_required`，不通过清锁重试。排查时查看 `script_state` 中的进程身份和日志，不按进程名批量杀进程。任意强杀监督进程、脚本主动 daemonize 或外部程序写入不属于成功保证。

工具发起的同项目有限脚本/构建准备会通过合作锁避免并发写入与消费。运行目录继续受部署锁、世界占用和活动读者规则保护，不能通过 before_run 覆盖其他世界的活动部署。该锁不是文件系统沙箱，也不约束外部生成器、其他项目的依赖读取或已开启的 watcher。

**脚本对源码的写入不会自动回滚。** 脚本失败会阻止本次 builder/启动，但源码中的半成品可能被下一次构建或已开启 watcher 读取。批量生成时暂停 watcher；单文件可使用上述包外临时文件和原子替换。多个文件的替换不构成事务，工具不承诺“生成成功前绝不热更”。

不要让脚本写入 `.mcpy/runtime`、`.runtime`、依赖缓存、全局游戏包或世界数据库。普通 build/package 使用源码生成结果，受管运行产物始终由原部署服务发布。资源文件更新、重载请求投递与游戏中实际生效是不同结果；组资源热更仍遵守现有不支持的限制。
