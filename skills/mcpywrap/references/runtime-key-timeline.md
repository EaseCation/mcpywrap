# 后台按键边沿时间线

本页为旧入口兼容参考。日常新任务统一使用 [runtime input](runtime-input.md)；旧行为仍保留，不自动更换后端。

各模式键名和组合字符串的完整对照见 [按键写法与兼容对照](input-writing.md)。

仅用于临时调试，不能把 `mcpy.*` 写入业务 Addon 或发布脚本。先通过公开 `runtime install` 更新当前会话，再用 `runtime player status` 查询 `capabilities.timeline`、`timeline.clocks` 和 `clock_source`；能力查询不安装组件。

`timeline` 适用于持续按住 W，同时独立按放 SPACE、A/D、SHIFT/CTRL。同一时刻严格按列表顺序调用内部键盘接口，不自动把修饰键移到前面。旧 `key` 保持整组持有与释放，旧 `sequence` 保持串行。

## 一次提交

在调用端保存 UTF-8 JSON 文件：

```json
{
  "schema_version": 1,
  "clock": "monotonic_ms",
  "events": [
    {"at": 0, "action": "key_down", "key": "W"},
    {"at": 300, "action": "key_down", "key": "SPACE"},
    {"at": 450, "action": "key_up", "key": "SPACE"},
    {"at": 1000, "action": "key_up", "key": "W"}
  ]
}
```

```text
mcpy --local --project <项目> runtime player timeline --session <sid> --file <计划.json> --request-id <32位小写hex> --json
mcpy --local --project <项目> runtime player status --session <sid> --operation <id> --details --json
mcpy --local --project <项目> runtime player cancel --session <sid> --operation <id> --json
```

远程将全局路由改为 `--remote <endpoint>`；文件在调用端读取，计划一次发送，事件在客户端调度。Python 对应 `mcpy.player.timeline(plan, request_id=None)`；只通过 `runtime py` 临时调用。

`at` 为相对首次可用执行回调的整数毫秒，必须非负且非递减。所有事件只有 `at/action/key`；每个事件只有一个已有 key 支持的键，不能填 `W+SPACE`。组合使用同一时刻的多个事件；列表也决定正常释放顺序。例如 W→CTRL 与 CTRL→W 保持不同的提交顺序。

提交前检查整个计划；未知字段、未知键/动作、无序时间、重复 down、没有 down 的 up、结尾未释放都拒绝，且不产生输入。CTRL/CONTROL 等别名按同一键码配对。最多 256 个事件，计划最大 120000ms；不支持 tick 时钟。

## 顺序与时间的边界

默认 `max_lateness` 省略或为 null：迟到继续按列表顺序提交，逐事件记录迟到。不重新排程、不延长保持时间；卡顿后多个事件可能集中到同一次回调，甚至 down/up 都没有被游戏消费。需要严格中止时显式填非负整数 `max_lateness`，单位毫秒；超过阈值返回 `deadline_missed` 并清理剩余输入。

执行使用游戏定时器和经过确认的单调时钟。Windows Python 2 可用 `windows.time.clock`；不能把其他平台的 CPU 时间或墙上时间作为回退。`started_at` 是执行端单调时钟的秒值，不是 Unix 时间，不能与另一台机器相减。输入接口没有批量原子性保证；固定提交顺序不等于固定实际间隔，也不等于固定输入消费阶段。

不计数或换算中国版 30 Hz 脚本回调、20 TPS 模拟、渲染帧或 AuthInput.clientTick。`dispatch_phase=unknown`，输入消费和实际游戏效果均需独立验证。

## 查询与失败清理

返回 `pending` 后保存 `id` 和规范化 `plan`，用 status 查询，不能靠 AI 多次 RPC 控制短时边沿。同 request_id 和相同规范化计划返回原操作；不同计划返回 `request_conflict`。操作历史仍保留最近 64 条，记录找不到不证明从未执行。

整个时间线占有玩家/UI 写权限，包括未按键和所有键已松开的等待区间；只读 snapshot/status 可继续。人工按键归属无法可靠区分，应使用无人同时操作的专用会话。

默认 status 返回 index/count、持键和终态等摘要；`--details` 返回完整计划、events 和 cleanup_events：

- `index` 为已尝试事件数；每条事件 index 从 0 起，与原列表对应。
- `started_ms/finished_ms` 是相对操作起点的引擎键盘接口调用边界；`lateness_ms` 相对计划 at，不能称为游戏消费时间。
- `accepted/result` 是接口回执；异常可能返回 accepted=null，即使接口抛错也可能已经按下。
- `held_keys` 是本计划仍承担清理责任的键；`released=true` 仅表示接口释放已确认，不证明已退出疾跑/潜行。
- `cleanup_events` 单独记录异常/取消清理，按实际按下的逆序释放，`release_of_index` 指向对应 down。清理日志最多 512 条；原事件最多 256 条。两类日志共同限制为 96 KiB，优先淘汰旧清理记录；`events_dropped/cleanup_events_dropped/logs_truncated` 明确报告丢失，不静默截断。异常消息最多 512 字符，截断时另记 `error_truncated=true`。

取消、菜单变化、世界/玩家失效、卸载、引擎异常及超时均停止后续事件并尝试释放本计划的键。释放失败报告 unknown 和 `unconfirmed_release_keys`，保持 busy；修复条件后用 stop 重试释放，不能重放计划。

墙钟执行上限为提交后 125 秒，在游戏回调中检查。游戏暂停或不处理调试命令时，不能保证当场执行超时、查询或释放；返回 unknown/unavailable，不宣称已释放。恢复后的回调先检查超时，再决定是否提交事件。

SHIFT/CTRL 按当前键位和游戏保持/切换设置处理。key_up 不必然等于 StopSneaking/StopSprint；控制层不直接改玩家姿态来匹配预期。所有操作保留 `effect_verified=false`。

## 可选实机验收

先准备已初始化的专用本地 Addon 项目及已安装的引擎，执行：

```text
python tests/manual_runtime_key_timeline.py --project <项目> --launch --engine-version <完整版本> --output <新的证据目录> --require-background
```

`--launch` 创建平坦生存世界并停止自己的会话；也可用 `--session <sid>` 附加专用平坦世界，结束后保留。脚本运行移动/跳跃与菜单操作，恢复朝向、释放输入；不恢复玩家位置，不适用于业务世界。缺少组件不安装、不切引擎、不退回桌面键鼠。

同一重叠配方重复三次，两种 W/CTRL 提交顺序各重复三次，再验证 W+SPACE 期间取消和菜单变化。保存实际边沿、采样位置/输入、键位与前台证据，必须观察真实跳跃以及 SPACE 松开后持续移动，不能只用 completed 判通过。观测探针用有限定时采样，不作为 tick 真值。此脚本不进入默认测试、CI 或正常启动。
