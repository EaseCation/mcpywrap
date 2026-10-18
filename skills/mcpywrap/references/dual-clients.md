# 本机双客户端联调

用于 Windows 或 Apple Silicon macOS 的两个玩家联调。先检查本机 `doctor --capabilities` 和命令帮助是否提供 `--clients`、`--group`，不要仅凭 Skill 版本推断已安装 CLI 的能力。

本地主客机还需要 `local-dual-client-manual` 能力，目前由 Windows 后端提供。外服双客户端按运行包的独立身份能力判断，不由本地主客机支持情况推断。

## 选择任务

- **同一个本地世界，两名玩家**：`run --clients 2`。第一名玩家是主机，第二个客户端加入主机。`--new` 新建世界；不是两个独立世界，也不是历史代码快照。
- **两个客户端进入同一外服**：`connect <host> --port <port> --clients 2`。服务器须允许无认证开发客户端；工具不部署或修改外部服务器的 Mod。
- **两个独立世界**：分别运行指定实例；同一份代码可以共享，运行中改依赖后应先退出相关世界再重新运行。

本次双客户端入口仅用于 `--local`。`--remote` 仍按远端单会话能力使用；不支持时不回退到本机。双客户端暂不提供两个真实账号登录，不反复复用同一 MCS 身份尝试绕过服务器登录限制。

## 启动并确认

以下命令的全局参数都放在子命令之前：

```text
mcpy --local --project <项目目录> --non-interactive run --clients 2 --no-gui --detach --json
mcpy --local --project <会话目录> --non-interactive connect <服务器> --port 19132 --clients 2 --detach --json
```

先保存返回的 `group` 和 `members`，再判断 `ok`。部分失败也可能已经启动主机；不要丢弃其会话 ID 或重新创建另一个世界。

本地组角色是 `host`、`guest`；外服组是 `client1`、`client2`。每个成员有自己的 `session`。主机玩家还有服务端执行能力，客机和外服玩家只有客户端能力。

不同客户端的实体 ID 可能重复。按组角色、会话 ID 和返回的玩家名称选择操作对象，不跨客户端复用实体 ID。

```text
mcpy --local --project <项目目录> status --group <组ID> --json
mcpy --local --project <项目目录> runtime capabilities --group <组ID> --json
mcpy --local --project <项目目录> logs --group <组ID> --source game --tail 100 --json
```

`running` 只说明进程阶段。只有 `connection_verified=true` 才表示已确认两个不同玩家加入同一世界；这仍不证明玩法正确。按项目需求在两个客户端分别执行一次验收脚本，并在主机服务端核对玩家列表或权威状态。不要用两个窗口、两张 HUD 截图替代联机验证。

本地主客机采用手动加入：工具启动主机和客户端 2 后返回 `waiting_for_join`，这不是启动失败。在客户端 2 选择“开始游戏”，点击提示中目标名称的“局域网世界”卡片，按需下载资源后加入；不要打开同名本地存档。首次菜单若只有“开始”和“更多选项”，选择“更多选项”进入正常菜单。工具会自动核验加入结果，CLI 也可使用 `status --group` 查询。未点击卡片不需要重启客户端；加入错误世界时先退出该世界，再选择指定主机。

先查询平台是否声明 `local-dual-client-manual`。当前 Windows 已接入本地手动加入；macOS 运行包尚未完成同等适配时会在启动前拒绝本地双客户端。外部服务器连接是独立能力，仍使用 `connect <host> --port <port>`；平台网络条件见[网络会话](network-sessions.md)。不要猜测本地联机端口或另开独立世界替代第二名玩家。

冷启动等待超时后，游戏可能仍在加载。先用 `status --group` 重新核验；如果两名玩家已经就绪，不必重开游戏。macOS 双客户端需要支持独立开发身份的原生运行包；旧运行包会明确拒绝此操作。

使用 `scripts/smoke.py --game --clients 2` 验收时仍需人工点击卡片；用 `--timeout` 留出操作和加载时间，例如 600 秒。验收脚本结束会清理本次创建的游戏，日常保留会话使用普通 run/status 流程。

## 始终明确操作对象

Python、输入、截图等操作仍使用具体成员的 `--session`，不会自动广播：

```text
mcpy --local --project <项目目录> runtime py --session <主机会话> --side server --file <服务端验收.py> --json
mcpy --local --project <项目目录> runtime py --session <客机会话> --side client --file <客户端验收.py> --json
```

执行前查询目标成员能力。禁止对客机发送服务端脚本。输入和截图的目标也必须是同一个已选择的成员；切换玩家后使用新的会话 ID。

游戏 Python 的结果/未知请求处理见[运行时调试](runtime-debug.md#执行-python-2)。普通玩家与 UI 动作使用[统一输入](runtime-input.md)，画面采集使用[截图/录制](capture.md)，始终绑定选中的成员。

## 更新代码

依赖增删、包身份或目录结构改变后，保存进度并重新运行联调组。普通源码变化可用明确的组热更：

```text
mcpy --local --project <项目目录> runtime reload python --group <组ID> --module MyMod.client.logic --side client --json
mcpy --local --project <项目目录> runtime reload python --group <组ID> --module MyMod.server.logic --side server --json
mcpy --local --project <项目目录> runtime watch --group <组ID> --side client
```

- `client` 更新两名玩家的客户端；`server` 只更新主机服务端一次。
- `both` 只用于确认可在两端执行的公共模块，不用于猜测端侧。
- 逐项检查成员、端侧的更新结果；部分失败或未知不等于整组成功，不自动重复执行有副作用的脚本。
- 当前组资源热更明确不支持（resource_sync_unverified），UI、粒子等不能通过主机单会话入口绕过；需要应用资源时重启整组并重新加入。
- 外服组不管理服务器提供的代码/资源，不对其使用本地组热更。
- 停止 watch 仅停止监控，不退出游戏；关闭管理面板也保留游戏。runtime watch/reload 不执行项目预处理；主机实际重新准备与客机重试的脚本时机见[项目脚本](project-scripts.md#自动执行时机)。

## 重试与退出

```text
mcpy --local --project <项目目录> restart --session <失败客机会话> --json
mcpy --local --project <项目目录> restart --group <组ID> --json
mcpy --local --project <项目目录> stop --session <客机会话> --json
mcpy --local --project <项目目录> stop --group <组ID> --json
```

重启后重新保存返回的会话 ID，旧 ID 只用于查历史。客机失败优先重试客机，不重建主机世界。主机有关联客机时，停止或重启整个组；工具先处理客机，再处理主机。

同一联调组的玩家身份会保留。主机代码或依赖改变后，客机重新加入时可能需要再次下载资源；不要手动清理全局包或修改运行记录。客机重试可加入主机当前已经加载的版本，源码改动是否已应用要另看提示；要应用依赖变化则重启整个组。

只结束自己启动或用户明确指定的会话。接管已有组用于观察，不自动取得退出其中所有游戏的授权。重要世界先在游戏中保存；Windows 的进程退出本身不代表新增的存档保存保证。

响应丢失时先用 `status --list --json` 找回组与成员；脚本结果为 `unknown` 时先检查原请求和日志，不盲目重发。
