# 本机双客户端联调

用于 Windows 或 Apple Silicon macOS 的两个玩家联调。先检查本机 `doctor --capabilities` 和命令帮助是否提供 `--clients`、`--group`，不要仅凭 Skill 版本推断已安装 CLI 的能力。

本地主客机需要 Windows 后端能力；`local-dual-client-auto` 表示可使用自动加入，旧版的 `local-dual-client-manual` 仅提供手动加入。外服双客户端按运行包的独立身份能力判断，不由本地主客机支持情况推断。

## 选择任务

- **同一个本地世界，两名玩家**：`run --clients 2`。第一名玩家是主机，第二个客户端加入主机。`--new` 新建世界；不是两个独立世界，也不是历史代码快照。
- **两个客户端进入同一外服**：`connect <host> --port <port> --clients 2`。服务器须允许无认证开发客户端；工具不部署或修改外部服务器的 Mod。
- **两个独立世界**：分别运行指定实例；同一份代码可以共享，运行中改依赖后应先退出相关世界再重新运行。

本次双客户端入口仅用于 `--local`。`--remote` 仍按远端单会话能力使用；不支持时不回退到本机。双客户端暂不提供两个真实账号登录，不反复复用同一 MCS 身份尝试绕过服务器登录限制。

Windows 0.5.3 起，角色的实际游戏资料保存在项目所在磁盘 `mcpy-profiles/<摘要>` 的独立目录，以兼容下载包脚本加载器；组记录与占用锁仍在项目内。旧资料自动复制迁移并保留备份，后续使用新目录。查看会话 `network.windows_profile` 或角色的 `windows-profile.json` 确认位置，不将此目录当作可随意删除的缓存。迁移未完成、归属冲突或已迁移目录缺失时先保留现场；不要删记录、回退旧身份或共享真实用户 AppData 来绕过。磁盘根目录不可写时会启动失败，不自动提权。

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

支持自动加入的 Windows 版本中，`run --clients 2` 默认返回 `joining`，worker 在后台完成加入和本地主机资源下载，再核验世界、网络身份与服务端玩家名单。等待 `status --group` 的 `connection_verified=true` 后再执行游戏调试。初始化阶段客机暂不接受其他 Python、热更或输入请求；不需要手动点击或抢占桌面焦点。

`run --clients 2 --join-mode manual` 保留原来的手动流程，返回 `waiting_for_join`。在客户端 2 选择“开始游戏”，点击指定名称的“局域网世界”卡片，按需下载资源；不要打开同名本地存档。首次菜单只有“开始”和“更多选项”时，选“更多选项”。旧联调组保留原来的加入方式，重启也继续沿用；切换方式先停止客机，再明确使用 `--join-mode`。

自动加入仅支持 Windows 本机。需要新版完整包的后台采集组件和 Windows 英文及游戏显示语言的 OCR 支持；当前菜单识别覆盖中文与英文。引擎窗口须持续渲染，最小化或菜单布局无法识别时不会回退前台操作。为初始化调试通道，每个隔离客机资料目录保留一个工具引导世界，随后自动退出并加入指定主机；它不是组件测试世界。

多个项目可以各自启动本地组。工具查询所属主机的实际 LAN 端口，并在本次客机内存中按指令结构定位和适配，不改磁盘游戏文件、不抢占其他进程端口。新引擎会自动尝试定位；零候选、多候选、端口归属不明确或读取校验失败都会明确拒绝，不使用旧版本地址猜测。不能保证任意未来引擎都兼容。`room_info.port`、`connect --port` 和 `serve --port` 都不是该监听端口的配置项。

失败时检查客机会话目录中的 `local-join.json`、`local-join-menu.json` 和游戏日志。主机仍保留，可修复后 `restart --session <客机>`；不要重放未知输入。手动模式不会自动适配多主机发现端口。

先查询平台声明的本地双端能力。Windows 提供自动加入和手动模式；macOS 尚未接入同等适配，会在启动前拒绝本地双客户端。外部服务器连接是独立能力，仍使用 `connect <host> --port <port>`；平台网络条件见[网络会话](network-sessions.md)。不要猜测本地联机端口或另开独立世界替代第二名玩家。

冷启动等待超时后，游戏可能仍在加载。先用 `status --group` 重新核验；如果两名玩家已经就绪，不必重开游戏。macOS 双客户端需要支持独立开发身份的原生运行包；旧运行包会明确拒绝此操作。

使用 `scripts/smoke.py --game --clients 2` 验收时会等待自动加入和玩家校验；旧工具或已有手动组仍需点击卡片。用 `--timeout` 留出初始化与资源下载时间，例如 600 秒。验收脚本结束会清理本次创建的游戏，日常保留会话使用普通 run/status 流程。

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
