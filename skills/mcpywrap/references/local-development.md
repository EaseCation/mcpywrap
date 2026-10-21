# 本地世界：启动、更新与停止

用于 Windows/macOS 本地世界；两名玩家直接读[双客户端](dual-clients.md)，外部服务器读[网络会话](network-sessions.md)。普通启动不需要加载输入协议、录制或所有平台安装细节。

## 启动与找回

```text
mcpy --local --project <项目> --non-interactive run --no-gui --detach --json
mcpy --local --project <项目> --non-interactive status --session <sid> --json
mcpy --local --project <项目> --non-interactive logs --session <sid> --source game --tail 100 --json
mcpy --local --project <项目> --non-interactive runtime capabilities --session <sid> --json
```

先保存 session、instance、config_path 和日志路径。status 的 running 只是进程阶段；world_ready 表示观察到世界就绪，正常 Mod 加载还需双端日志或业务探针。source 可选 game/engine/worker；准备脚本输出位于 worker 日志及其 script_log。

`--no-gui` 只抑制辅助窗口，游戏仍需图形会话/GPU。人工 run 默认有日志小窗，完整项目页用 ui。Qt 准备阶段可看任务和取消自己发起的准备；关闭管理/调试窗口不代表游戏已退出。

| 意图 | 用法与结果 |
|---|---|
| 打开默认世界 | run；默认按创建顺序选择可用实例，失败创建不会无提示成为默认 |
| 选择已有世界 | `run <实例ID前缀> --no-gui --detach --json` |
| 查看世界实例 | `run --list --json`；与 `status --list --json` 的会话/组列表不同 |
| 新建世界 | run --new；种子/地形等参数见[世界设置](instance-world-settings.md) |
| 复用已运行世界 | 返回 already_running，不重新部署、不运行 before_run；检查 source_matches/hint |
| 重新加载当前项目代码 | 停止相关会话后 run 原实例；也可 `restart --session <sid> --json` |
| 启动响应丢失 | 同一项目 status --list 找回，不立刻再次 --new |
| 明确删除世界 | `run --delete <前缀> --force --json`；仅用户要求删除时使用，不作为修启动的方法 |

restart 会产生新 session，世界 ID 保留；需要 MCS 身份的会话按提示重新 run 并提供本次身份。旧 session 可查历史，不能继续向它发送输入。实例是世界，session 是一次进程运行，group 是联调成员关系。

## 持续日志

```text
mcpy --local --project <项目> --non-interactive logs --session <sid> --follow --source all --format jsonl
mcpy --local --project <项目> --non-interactive logs --group <gid> --follow --source all --format jsonl
```

`--follow` 是只读的本机持续订阅，不加 `--json`。`--source all` 同时接收 game（脚本系统）、engine、worker；也可单选来源。`--tail` 为每个来源的初始历史行数，0 表示从订阅时刻开始；历史回读最多 256 KiB，之后逐字节增量读取，不按文本去重。关闭订阅保留游戏；全部成员结束后排空日志并退出。

`--format jsonl` 每行是独立 JSON：`schema_version=1`，`event` 为 `log/state/reset/end`。log 含 session、可选 role、source、text；text 可以是半行并保留 UTF-8 边界。state 含 session/state；reset 表示文件轮换或截断；end 表示已读到会话结束。不支持此选项的旧 CLI 需要升级，不能用快照轮询伪装连续流。

每轮每个来源最多读取 64 KiB，约每秒刷新一次会话状态；读取后立即关闭文件，不长期占用 Windows 日志句柄。文件迟到时从出现后的开头读取，轮换或观察到截断后发出 reset 并从新文件开头继续；轮换前尚未读取的旧文件内容不保证补回，同一文件在两次读取之间被截断又增长到原偏移以上也无法可靠检测，不承诺归档级无损追踪。会话全部结束后排空剩余内容；末尾不完整的 UTF-8 字节按替换字符输出。读取失败在 stderr 报错并以非零退出，stdout 中已输出的 JSONL 保持有效。Ctrl+C 或消费者断开只释放订阅，不写 stop 请求。

## 代码部署与世界进度

**世界保存进度，重新运行使用当前项目代码；--new 不保存旧代码快照。** Addon 无论依赖数量都先组装，再通过受控部署给游戏读取；修改源码不等于活动游戏立即看到新内容。

| 变化/需求 | 应采取的操作 |
|---|---|
| 未改代码，启动另一个独立世界 | 可共享同版部署；同一个实际世界路径仍独占 |
| 有变化，但已有会话被 run 接管 | source_matches/hint 说明当前包文件是否一致；新源码没有因接管而应用 |
| 修改已加载 Python 模块 | 按端侧使用 runtime reload/watch，见[调试](runtime-debug.md) |
| 增删依赖、包身份或结构变化 | 停止相关读者后重新 run；需要恢复依赖时先 sync |
| 另一个世界仍读同一部署 | 普通换版或单会话热更可能被拒绝；不能 --new、改 UUID 或清锁绕过 |
| 运行输出被外部改写/恢复未完成 | 保留文件和诊断，先查 status/logs；见[故障定位](troubleshooting.md) |

本机世界不会自动保留多版本 A/B 部署。独立目录也不自动意味着 Windows 引擎按相同 UUID 加载不同版本；不要通过手工链接或改 UUID 构造未经支持的隔离。

根 before_run 和[依赖消费者准备](consumer-prepare.md)都只在真正准备本地进程时执行。`source_matches=true` 只比较当前可组装文件，不证明包外素材已经生成；根任务与依赖准备的配置分别见[项目脚本](project-scripts.md)和消费者准备页。

## 就绪与结束

已有目标会话后，执行游戏 Python、验证模块或热更才读[运行时调试](runtime-debug.md)。world_ready 尚未到达时继续有界查询；连接可用与脚本系统完成初始化不是同一状态。

```text
mcpy --local --project <项目> --non-interactive stop --session <sid> --json
```

停止 watch 只结束监控，不退出游戏。stop 在准备阶段请求取消，在游戏阶段按已有后端退出；只取消本次拥有的启动，等待别人的启动超时不获得停止权限。遇到退出未确认或 recovery_required，保留占用和现场，不手动删锁、改 PID 或批量杀进程。

重要存档先在游戏中正常保存。macOS 后端请求保存退出；Windows 进程退出本身不等于已验证世界保存。测试结束确认自己的会话已 exited，用户要求保留则报告 session。组成员的停止/重启规则见双客户端页，不对有活动客机的主机单独 stop。

## 一次性自动验收

需要“新建独立测试世界、双端探针、收集日志并清理”时使用已有辅助脚本；只想保留/复用游戏不要使用它：

```text
python <skill>/scripts/smoke.py --command <本机mcpy命令> --project <项目> --local --game --client-file <客户端验收.py> --server-file <服务端验收.py> --expect-log <加载标记> --timeout 90
```

smoke 会 package、创建新世界、等待就绪、各执行一次探针并清理本次创建的会话。只打包省略 --game；无业务标记/探针的结果不能当作业务验收。含预处理的项目 package 与 run 各执行自己的 hook，这是两个操作，不保证生成器只执行一次。
