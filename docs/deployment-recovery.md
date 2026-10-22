# Windows 全局包部署与恢复

普通本地世界共享 Windows 游戏的全局包目录。引擎按包 UUID 选择内容，项目目录不同并不会隔离相同 UUID；工具会在启动前检查全部相关行为包与资源包，避免加载历史代码。

工具在项目 `.runtime/deployment-owner.json` 保存本机部署身份，在全局 `.mcpywrap/ownership.json` 保存链接归属与迁移关系。删除世界保留部署登记；不要把删实例、改 UUID 或删除锁当成恢复启动的方法。

已有失败实例也能获得引导：普通 `run` 遇到没有可用实例时，会读取最后一次部署失败并重新检查当前现场。管理页打开/刷新项目后会显示恢复说明和“迁移并重试”入口，不需要先制造一次新失败。历史记录缺失或冲突已经消失时，不会把旧错误当成当前问题；检查不会改写历史或启动游戏。“复制修复命令”复制的是只读预览命令，执行变更仍需确认具体方案。

## 纯命令行操作

在交互终端中使用 `mcpy run --no-gui`，遇到可明确归属到一个旧项目的迁移冲突时，工具直接显示旧、新项目、行为包与资源包范围、原会话或联调组，以及具体链接变更。输入 `y` 确认后迁移并重试原世界；回车默认取消，退出码非零，不修改部署。无需手工复制计划摘要，也不会打开 Qt 窗口。

前台运行在重试后继续显示会话状态；使用 `--detach` 则返回新会话及状态、停止命令。进程启动不等于世界已就绪，迁移仍按正常世界就绪流程提交。涉及联调组时重试整个原组。

有活动游戏、未知占用、归属证据不足或多个旧项目冲突时，不弹出无法安全执行的确认。终端说明阻塞对象并提供只读检查入口，处理后重新预览。

独立的部署命令默认只预览。需要在终端完成操作时加 `--interactive`：

```powershell
mcpy --local --project 'D:\Mods\new-project' deployment repair --interactive
mcpy --local --project 'D:\Mods\new-project' deployment migrate --from 'D:\Mods\old-project' --session '<failed_session>' --interactive
mcpy --local --project 'D:\Mods\old-project' deployment retire --interactive
```

这些命令先显示当前预览，再要求一次默认否的确认。内部使用本次预览摘要执行并重新核验；确认期间现场变化会返回 `plan_stale`，不自动扩大范围或重复尝试。`inspect` 始终只读，会为已有失败记录补上带会话目标的迁移预览命令。

`--json`、`--non-interactive` 和输入重定向时不读取确认输入；`--interactive` 与这些模式或 `--apply/--expect` 组合会明确报参数错误。脚本继续使用下面的预览及 `--apply --expect` 协议，JSON 字段保持兼容。

## 默认处理

- 同项目已登记链接直接复用；证据完整的旧链接、来源仍存在的缺失链接可自动修复。
- 项目拆分或搬迁后，跨目录同 UUID 首次需要确认迁移。确认范围包括具体来源与包集合，不授权清理其他项目全部资源。
- 已迁移包的旧项目入口会显示 `deployment_relocated`，提示从新入口运行；不会自动抢回。
- 未知内容、实体目录、外部改写、身份缺失和占用不明会保留现场并给出诊断。未知进程不会被批量终止。

只读检查不构建、不执行 hooks、不安装依赖，也不自动恢复事务。地图的依赖身份从已安装的依赖元数据读取；依赖未同步时先按诊断执行 `sync`。

## 检查与修复

```powershell
mcpy --local --project 'D:\Mods\new-project' deployment inspect --json
mcpy --local --project 'D:\Mods\new-project' deployment repair --json
```

`inspect` 始终只读。`repair`、`retire`、`migrate` 默认预览，返回 `changes/conflicts/issues/blockers/can_apply`、`plan_digest`、结构化 `apply_argv` 和可复制的 PowerShell `apply_command`。

确认具体变更后，执行预览给出的完整命令：

```powershell
mcpy --local --project 'D:\Mods\new-project' deployment repair --apply --expect '<plan_digest>' --json
```

`plan_stale` 表示预览后相关现场或启动意图已变化，应重新预览；不循环重放旧命令。修复可以重建已核验的缺失/损坏本机身份，以及恢复已确认退出的部署事务，不会构建一份新运行产物冒充原内容。

## 从旧项目迁移并重试

启动冲突会返回双方路径、推断归属和后续操作。保存该次失败的 session，再预览：

```powershell
mcpy --local --project 'D:\Mods\new-project' deployment migrate --from 'D:\Mods\old-project' --session '<failed_session>' --json
```

本地联调组改用 `--group <group_id>`，与 `--session` 互斥。网络会话和其他后端不使用此入口。旧项目可以只剩 `.runtime` 和历史运行产物，不要求仍有 `pyproject.toml`。

目录搬迁导致旧的已登记链接悬空时，明确的身份、UUID 登记与可完整还原的链接快照可用于显式迁移。恢复不创建旧源空目录；未登记悬空链接不会仅凭名称被认领。联调组确认绑定原组配置，配置变化会要求重新预览。

终端可使用 `--interactive` 预览后确认；脚本执行返回的 `apply_argv` 或 `apply_command`。工具重新核验现场、按原世界和引擎意图创建新会话，执行正常准备，然后将旧链接退役与新链接发布纳入该次启动事务。需要 MCS 身份时重新走现有身份获取流程，不复用持久化凭据。

返回 `running` 表示进程启动，仍需查询 `world_ready` 并验证 Mod 内容。世界就绪后提交；此前失败且确认游戏退出时恢复原链接、归属及配置。游戏身份不明、退出未确认或恢复对象被外部修改时，保留事务与占用，不强行覆盖。

迁移只处理部署链接及当前启动配置；源文件、旧运行产物和旧世界保持原位。GUI 的“查看冲突详情”“迁移并重试”“复制修复命令”使用相同服务。

## 退役全局部署

不再使用旧项目时，先预览其已核验链接：

```powershell
mcpy --local --project 'D:\Mods\old-project' deployment retire --json
```

对归属未知的链接，可以明确选择一个或多个实际链接，预览后按摘要执行：

```powershell
mcpy --local --project 'D:\Mods\new-project' deployment retire --link 'C:\Users\name\AppData\Roaming\MinecraftPE_Netease\games\com.netease\behavior_packs\old-link' --json
```

只接受全局包目录内可核验、可恢复的目录链接。实体目录和来源已丢失的显式退役对象会保留；不会递归删除源文件或世界。

## 错误与兼容

错误保留 `error/code/hint`，增加 `details/actions/operation_id`。worker 日志包含脱敏后的失败摘要；`status` 保留结构化诊断。操作记录在全局 `.mcpywrap/operations`，未提交事务在 `.mcpywrap/transactions`，不手工删除这些记录。

兼容 Windows 默认 GBK：终端沿用当前编码，中文正常输出，无法表示的字符转义显示；JSON 使用 ASCII 转义，解析后保留原始 Unicode 路径。项目/全局登记、事务与 worker 日志明确以 UTF-8 读写，不依赖系统默认文件编码，也不要求启用 `PYTHONUTF8`。含 GBK 无法表示字符的路径，自动化应使用 JSON 的 `apply_argv`，GUI 直接使用结构化操作。

| code | 处理 |
| --- | --- |
| `pack_conflict` | 检查全部冲突，选择迁移或针对性退役 |
| `ownership_changed` / `link_modified` | 核对归属和实际目标；`repair` 预览会说明可重建内容 |
| `busy` / `deployment_in_use` | 当前操作或会话仍占用，等待或保存退出后重试 |
| `occupancy_unknown` | 进程归属或退出状态无法核实，保留现场 |
| `recovery_required` | 对拥有该事务的项目执行 `deployment repair` 预览完整恢复 |
| `deployment_relocated` | 使用提示中的新项目入口 |
| `plan_stale` | 重新预览，不直接重放旧摘要 |

现有 `links.json` 布局和链接命名保留；历史单文件链接事务仍可恢复。旧工具对链接表的改写会在新版启动时核验，一旦与持久归属不符就停止，不能保证旧二进制理解新版归属规则。普通单客户端不提供独立资料目录隔离。

部署恢复的自动化与隔离实机验证见 [测试入口](../tests/README.md#全局部署恢复)。
