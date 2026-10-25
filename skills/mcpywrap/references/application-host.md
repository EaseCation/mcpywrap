# 本机 App 接入

适用于 Minis、Termux 或其他能访问共享作品目录的开发工具。使用标准 `mcpy` CLI；HTTP `/v2` 是宿主协议，不需要为某个 Agent 安装专用构建器或常驻代理。

## 首次连接

新版页面名为「开发」，旧版名为「开发工具」；使用同一套命令与协议。

1. 用户打开 mcpy App 并授权作品目录后，新版默认开启仅监听 `127.0.0.1` 的开发连接；已主动暂停或使用旧版时，在「开发」恢复连接。页面直接显示本机地址、配对码和有效期，可以复制配对码、标准命令，或可选的 AI 说明。普通终端无需 AI；模型账号只在使用 Agent 时需要。
2. 开发环境安装 Python、Git 和正式 `mcpywrap`。Minis 的 PRoot 使用 Alpine；优先使用其包管理器提供的 Python，再按标准 pip/uv 安装。解释器与虚拟环境放在该应用私有 Linux 目录，不能放在共享存储上。
3. 让用户将内部存储 `mcpy` 目录挂载为可读写目录。Minis 1.14 在设置 → Mount External Folders 中选择目录，并授予 Minis 自身的“所有文件访问”；仅有文件夹选择授权仍可能看不到其他 App 写入的文件。常见路径为 `/var/minis/mounts/mcpy`，以实际探针结果为准；不能把同名私有副本当作共享目录。
4. 完整安装技能并配对：

```sh
mcpy skill install --directory /var/minis/skills/mcpywrap
mcpy host pair --url http://127.0.0.1:17653 --code <App给出的短时配对码> --workspace <实际挂载路径> --label Minis
mcpy --project <挂载路径>/projects/<作品> host status --json
```

已有技能更新使用 `skill install --replace`。配对会验证双向读写，并等待用户通过临时确认卡、通知动作或 App 页面允许连接。有悬浮权限时可直接在开发工具上方确认，无权限时使用通知；不需要常驻悬浮图标。命令将长期凭据保存到私有配置，不打印到对话；不要读取或复制该配置中的 token。

## 日常开发

**正常启动直接运行，用户继续留在开发工具中。** 配对后执行 `mcpy --project <作品目录> run --no-gui --detach --json`，App 负责游戏画中画。不要将 `android-open`、`am start`、`mcpy://service/start` 或切换 App 到前台当作启动前置步骤。`background_launch=unknown` 和历史失败都不代表本次必然失败；没有明确 blocker 时正常提交 run，以本次结果为准。恢复 URI 只是失败后的人工入口，出现在能力响应中不意味着需要调用。

工程命令绑定后继续使用 `init/mod/add/sync/build/package/run/status/logs/stop/runtime/screenshot` 标准命令，先查宿主能力；不加 `--local`。`modsdk` 补全库管理与 `skill` 安装属于开发端工具操作，不要求宿主在线，也不会作为工程降级入口。CLI 只负责输入、结果和宿主要求的工具准备，解析与组装必须在 App 的核心中执行。运行相关操作始终指定作品与会话。作品在开发环境中通过 `--project` 选择，App 的「开发」页不绑定作品。

客户端与 App 核心可能独立更新。需要执行准备阶段时，辅助代码必须与 App 的核心版本一致；按错误指引升级后重试，不修改配置绕过版本核对。Git/pip 安装、项目 hooks 和消费者准备在发起端执行，按 App 给出的阶段顺序交回结果，不能提前执行所有 hooks 或跳过 before_archive。

项目源码、依赖资源和输出都在真实共享目录内。原生工具扩展留在 PRoot 环境，不进入游戏行为包。当前宿主提供显式构建、Python 热更与重启；`dev`/`runtime watch` 未列为能力时，不创建另一套自动构建代理。修改后按标准生命周期应用源码；不要把启动成功或 running 当成模组已验证，以双端实际日志、断言和游戏截图验收。

游戏状态中的 `pip` 表示 Android 画中画（Picture-in-Picture），与 Python 的 pip 包管理器无关，也不表示脚本环境就绪。小窗验收检查 `pip=true`；游戏就绪与双端源码初始化另查世界状态、客户端/服务端探针和日志。游戏 Surface 截图用于检查完整渲染；要确认小窗位于 Agent 聊天页之上，还需检查手机实际窗口状态。

## 连接失败与恢复

- App 不可达：立即暂停自动操作，请用户手动打开 mcpy，确认开发连接已开启，恢复后即可返回原工具；也可向用户展示恢复链接 `mcpy://service/start`，不自行调用唤起命令。App 恢复此前已启用、尚未主动暂停的开发模式；否则显示连接页供用户开启。系统不允许唤起时请用户打开 App。仅凭连接失败不能判断进程退出、服务关闭还是端口错误；`host status` 的最后已知信息不是实时状态。不会改为本地核心执行。
- Git 环境：Minis 1.14 的部分 rootfs 带有无效的 `core.createObject=copy`。若 Git 原样报告 `invalid mode for object creation: copy`，在该 Linux 环境检查 `git config --show-origin --get core.createObject`，将报告位置的值修正为 Git 支持的 `rename`（系统配置可用 `git config --system core.createObject rename`）；不要修改手机 App 或另一台电脑的 Git 配置。
- 配对恢复：新宿主声明 `pairing.resume=true`。CLI 将握手保存在私有配置目录，目录挂载修复或连接中断后重试同一条配对命令，会继续原请求；开始请求与验证回复丢失也不会重复授权。邀请有效一小时，发起请求及等待确认各有十五分钟窗口。明确过期或宿主身份变化时才重新生成配对码。
- 连接中断：`mcpy host status --recent --json` 离线查看本客户端最近的请求、操作 ID、最后观察到的状态及时间；`cached=true` 表示缓存。用 `mcpy host status --operation <id> --json` 查询原任务，或 `mcpy host resume --operation <id> --json` 继续等待并交回已完成的准备结果；不会新建操作。
- 准备阶段结果未知：CLI 在私有配置目录持久记录执行凭据。中断前已保存的结果可重传；只有“开始执行”而没有结果的阶段明确报 `preparation_unknown`，先检查原进程与输出，不重跑脚本。
- App 重启：未完成任务标为中断，不自动重放。结果未知时不要再次发送相同有副作用代码。
- 后台启动等待用户：`operation_state=waiting_user` 表示准备结果已保留。出现 `needs_user_action=true` 或 `next_action=ask_user` 时，立即停止自动重试，将 `user_message` 告诉用户并等待明确回复。不要继续 run/restart/build、新建世界、循环轮询，也不要改用其他唤起或权限绕过手段。检查 `prepared/game_started/reason/hint/actions`：没有游戏进程时不能声称游戏正在后台运行；已有进程时只需恢复画面。请用户切回 mcpy（也可打开 `mcpy://service/start`），App 自动继续同一次启动；收到用户明确确认后，再用原 `operation_id` 执行 `host resume` 查询。不重复构建、执行 hooks 或 `run --new`。未启动请求保留十五分钟，过期后使用原实例 ID 重试；已有进程不因画面恢复等待过期而退出。
- 撤销：`mcpy host disconnect` 撤销 App 授权及本地绑定；App 不可达时 `--offline` 只移除本地绑定，之后仍需在 App 撤销连接。

## 启动与失败诊断

运行前用 `mcpy host status --json` 或 `mcpy --project <作品目录> doctor --json` 查看 `launch_preconditions`。`ready=true` 表示没有已知阻塞项；厂商后台限制为 `unknown` 时仍须以真实启动证据为准。缺权限时按 `hint` 与系统设置 action/URI 提示用户，不用 Shizuku、辅助功能或另一个启动器绕过授权。

`status` 的 `reported_phase` 是原始上报，`state` 是结合进程与记录新鲜度的观察结果。没有进程确认时 `heartbeat=null`，部署的 `created_at` 不代表游戏存活。`unknown` 不等于系统拒绝，`unresponsive` 不等于崩溃；检查 `bootstrap`、`launch_receipt`、`process_alive`、`process_exit` 和 `engine_log_tail`。

小米系“显示悬浮窗”与“后台弹出界面”是不同权限。`vendor_background_launch_denied` 表示已查询到本应用的厂商权限被拒绝；按返回的设置入口，请用户允许“后台弹出界面”。其他系统无法查询时仍报告 `unknown`，不猜测。用户暂不授权也可以每次返回 App 继续已准备的请求；不要通过其他工具绕过授权。

`host resume --operation <id>` 不重放启动。`waiting_user` 时先提示用户操作，返回 App 后再查询原任务。若任务结果未知但同一会话后来已确认运行，可返回 `reconciled=true`；否则返回最新 `observation`。修复原因后若需重新启动，使用诊断中的原 `instance_id`，不要反复 `run --new`。

日志可用 `--source all` 聚合 game/engine；持续日志分源维护游标。截图省略 `--output` 时自动保存到作品 `captures/`，返回 `image` 路径且不覆盖已有文件；加载期截图不证明模组已就绪。实例列表使用 `run --list --json`，不要从协议操作名 `instances.list` 推断不存在的 CLI 子命令。

补全库版本目录使用 `mcpy modsdk --list --offline --json` 只读缓存，`--refresh` 显式联网刷新，整体最多等待 12 秒。ModSDK API 与开发知识使用独立的 https://github.com/EaseCation/netease-modsdk-skill ，按其 README 安装完整技能与查询资料；不加入 mcpy 或游戏包的依赖。


## 筛选日志与会话交接

```sh
mcpy --project <作品目录> logs --session <sid> --filter '[组件前缀]' --summary --json
mcpy --project <作品目录> logs --session <sid> --source client --filter '控件路径' --tail 50 --json
mcpy --project <作品目录> logs --session <sid> --since-ms <Unix毫秒> --until-ms <Unix毫秒> --json
mcpy --project <作品目录> logs --session <sid> --follow --filter '[组件前缀]' --format jsonl
```

`--filter` 是区分大小写的字面匹配，不是正则表达式。先筛选，再取 `tail`；`--summary` 统计扫描范围内完全相同的消息，客户端和服务端分开计数。统计模式不与持续跟随同用。每源每次最多扫描 512 KiB，响应提供 `available/scanned_lines/matched_lines/scan_truncated`；摘要超过 `tail` 时有 `summary_truncated`。无匹配只能说明该范围内没找到，不能证明模组正常。时间筛选不猜测缺少时间戳的消息，排除数量见 `excluded_without_timestamp`。持续读取按原始文件游标推进，未匹配记录也会推进游标。

宿主在 `log_query` 中声明筛选能力，旧 App 缺失能力时明确要求升级，不静默忽略参数。桌面本地也支持字面过滤和统计，快照扫描 512 KiB，持续跟随首次历史读取为 256 KiB；Windows 旧 HTTP 服务继续使用原接口，由客户端筛选最近 10000 行，并明确返回该扫描范围。端侧与毫秒时间筛选需要支持结构化日志的宿主，不能从桌面原始文本猜测。

`restart` 返回新 `session`、`previous_session` 和 `session_changed=true`。立即更新后续日志、截图、Python 调试的目标；旧会话仍用于历史查询。等待用户恢复的重启请求同样携带会话交接信息。

## 启动证据与等待策略

App 的 `run/restart --launch-timeout <秒>` 配置进程及画中画的确认等待，默认 45 秒，范围 5–120 秒；须由 `launch_options.ack_timeout` 声明支持。世界加载使用独立的 300 秒限制，超过确认等待不会自动重放启动、重新构建或新建世界。桌面及旧 Windows 服务未声明此参数时明确拒绝，保持原启动策略。

`status.launch_timeline` 返回已记录的部署、Activity、引擎及游戏阶段，各项有 `observed_at/age_ms/elapsed_ms/since_previous_ms`，保留有界历史并报告 `truncated`。旧会话只返回真实存在的记录，不补造阶段。`clientReady/serverReady` 描述宿主调试初始化证据，不证明任何业务系统或 UI 正常。

`launch_preconditions.checks.background_launch.last_observation` 提供最近后台尝试的结果、时间、年龄和 `same_environment`。前台恢复成功不会覆盖先前后台失败；历史结果不能代替当前权限检查，`unknown` 仍表示无法判断当前权限。App 更新或系统环境变化后的历史只作参考。离线服务信息和最近操作记录提供查询时计算的 `age_ms`，不把缓存包装成实时状态。

mcpy 提供工程管理、会话控制和原始诊断证据；ModSDK API 语义、UI 文件规则及业务修复由独立 ModSDK skill 和开发者负责。不要根据“无报错”“画面上有文字”推断业务代码已生效，也不要为模组引入 mcpy 专属健康上报依赖。


需要用户接手的结果使用统一字段：`needs_user_action=true`、`next_action=ask_user`、`retryable=false`、`retry_policy=after_user_confirmation`、`user_message` 和 `agent_instruction`。宿主不可达时也适用，但不能据此声称准备已完成、游戏已启动或权限确实被拒绝。有 `operation_id` 时附带 `resume_command`；先等用户确认，再查询原任务，不重新提交有副作用操作。普通终端和 JSON 输出都包含该指引，即使 Agent 没有加载本 skill，也应能直接看到下一步。


后台连接容易暂停时，请用户在 mcpy 的“开发”Tab 打开省电设置。小米系统选择“无限制”；该设置影响后台联网和 CPU，与“后台弹出界面”权限分开。只引导有外部工具连接需求的用户，不要求普通编辑或手动运行也授权。后台策略无法通过标准接口可靠核实时保持未知，不把打开过设置当作已经授权。Minis、Termux、编辑器与 HTTP 客户端使用相同的连接机制；AI 只是可选的操作方式。


宿主专用的 `--launch-timeout`、毫秒时间筛选及客户端/服务端日志来源，只在当前工作区已绑定宿主时显示在对应命令帮助中。此选择与运行 CLI 的操作系统无关：桌面也可以操作已绑定手机的工作区，手机中的普通本地工作区也不会自动变成宿主模式。`host status --binding-only --json` 只读当前工作区绑定，不访问宿主。
