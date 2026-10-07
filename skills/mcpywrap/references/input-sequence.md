# 连续动作的时间编排

本页为旧入口兼容参考。日常新任务统一使用 [runtime input](runtime-input.md)；旧行为仍保留，不自动更换后端。

键名、别名、VK/SC/E0 格式以及游戏内/桌面的兼容区别见 [按键写法与兼容对照](input-writing.md)。

所有连续执行都先生成计划，没有“普通”和“精确”两种模式。Windows 的 `input-sequence` 和游戏内部的 `runtime player sequence` 共用时间编排规则；只按任务选择输入后端。

- `at_ms` 是相对序列起点的计划开始时间，整数毫秒，可省略。
- 省略时按 **前一步计划结束时间 + 本步 delay_ms（默认 0）** 自动生成；第一步的前置结束时间为 0。
- `at_ms` 和 `delay_ms` 在同一步中互斥；可在不同步骤中混用。计划保持列表顺序，不自动重排；显式时间不能早于上一步计划结束。
- 后端不会在原有计划中偷偷插入 100 ms 间隔。若动作、系统调度或保护检查耗时导致迟到，实际执行时间可以晚于计划，不能把计划当作测量值。
- Windows 的 down/up、move、relative、wheel 是提交瞬间事件，计划时长为 0；需要保持按下时，在对应 up 事件设置 `delay_ms` 或 `at_ms`。游戏内步骤则使用其 `hold_ms / duration_ms` 或默认时长计算计划结束。

## 选择后端

| 任务 | 入口 | 执行时钟与限制 |
|---|---|---|
| 移动、进食、射箭等游戏语义操作，需要后台执行 | `runtime player sequence` | 游戏定时器/tick；每步观察与释放校验，不能保证 0–20 ms 精度 |
| 后台保持一个键，同时独立按放其他键 | `runtime player timeline` | 单调毫秒计划；严格列表顺序、迟到默认继续，详见 [按键时间线](runtime-key-timeline.md)；不提供模拟 tick 对齐 |
| Windows 真实键鼠快切、输入竞态和 0–20 ms 时序测试 | `input-sequence` | Windows `SendInput`；会激活并占用游戏前台，返回输入提交时间 |

只有任务允许游戏占用前台时才用 Windows 入口。它不需要 `runtime install`。调用端及远程 Windows 执行端均需 CLI 0.3.19+；先检查 `input-sequence --help`，bootstrap 可要求 `input-sequence` 能力，远程执行端也必须报告该能力。旧 CLI/服务缺少入口时明确报错，不拆成多个 key/mouse 调用或回退本机。现有单次 `key` / `mouse` 保持原有参数、最低时长及返回字段。

游戏内编排由调用端 0.3.19+ 的 `runtime install` 注入，远端只需兼容的 `py` 通道；更新 CLI 后重新 install。UI 节点操作仍逐次观察和执行，不把旧节点 ID 排进玩家或 Windows 队列。

## 一次请求提交 Windows 编排

调用端保存 UTF-8 JSON 列表，例如 `plan.json`：

```json
[
  {"type": "key_down", "key": "2"},
  {"type": "key_up", "key": "2", "delay_ms": 5},
  {"type": "mouse_down", "button": "right", "at_ms": 10},
  {"type": "mouse_up", "button": "right", "delay_ms": 5}
]
```

自动生成的时间为 `0 / 5 / 10 / 15 ms`。鼠标 down/up 使用当前位置，不移动准星；必须先确认鼠标位于游戏客户区、场景和手持物品适合测试。

这与逐项显式填写 `at_ms: 0, 5, 10, 15` 是同一计划。若所有事件都省略 `at_ms` 和 `delay_ms`，这些瞬间事件会全部排在 0 ms，不会自动补按键保持时间。组合键需先列修饰键 down，最后逆序列出 up；普通点击则配对 mouse_down/up。

```powershell
mcpy --local --project <项目> input-sequence --session <sid> --file plan.json --width <客户区宽> --height <客户区高> --json
```

远程换为 `--remote <endpoint>`。文件在调用端读取，只发送事件内容，整段计划通过一次执行请求完成；能力检查可能另有只读请求。也可用 `--events '<JSON列表>'`，与 `--file` 二选一。

| type | 额外必填字段 | 语义 |
|---|---|---|
| key_down / key_up | key | 单个键名或 VK/SC/E0 代码；组合键列出各键的 down/up |
| mouse_down / mouse_up | button | left/right/middle，使用当前指针位置 |
| move | x, y | 参考客户区内的绝对坐标 |
| relative | dx, dy | 相对位移；效果受系统及游戏输入设置影响 |
| wheel | delta | 滚轮量，通常 ±120 |

事件最多 256 个，整个计划不超过 10 秒，JSON 不超过 64 KiB。所有 down/up 必须配对，禁止跨请求保持按下。含任何鼠标事件时必须提供参考截图的客户区宽高。

相邻且计划时间相同的键盘/鼠标按钮事件会按列表顺序合并为一次 `SendInput`。移动/滚轮是批次边界，使之后的点击可以重新检查实际指针位置。整个计划只做一次前台准备，计时起点在准备完成之后；进程启动、网络和激活开销不计入事件间隔。

## 读结果与处理失败

`plan` 返回补齐 `at_ms` 的计划，`events` 返回实际尝试过的事件：

- `scheduled_ns / send_started_ns / send_finished_ns`：执行端 `perf_counter_ns` 时钟，分别为计划时刻及 `SendInput` 调用边界；不是 Unix 时间，不能与另一台电脑的时钟相减。
- `actual_ms / lateness_ms / interval_ms`：相对起点的提交时刻、迟到量、相邻事件提交起点间隔。
- `batch / batch_size`：同批次共享起止时间，批次内 `interval_ms=0` 仅表示同一次提交，不表示 Windows 或游戏零间隔处理。
- `accepted`：Windows 是否完整接受此批事件；部分提交时为 `null`，`batch_inserted_count` 只说明该批插入数量，不猜测逐事件身份。
- `released / cleanup_events`：是否已释放本计划持有的输入，以及异常清理的独立时间记录。清理事件的 `release_of_index` 指向原按下事件，不占原计划步骤，也不用于测量正常快切间隔。

例如上面的计划，测“槽位键按下 → 右键按下”时，用对应两条事件的 `(mouse.send_started_ns - key.send_started_ns) / 1e6`。不能直接用右键记录的 `interval_ms`，因为它的前一条事件是键盘抬起；也不能用整条 CLI 的耗时或 `at_ms` 差值冒充实测值。只有两个相关事件都 `accepted=true` 时才判读该样本；同批事件的 0 ms 只说明一次批量提交。

可指定 `--max-lateness-ms N`：某批次在提交前已迟到超过 N 时停止后续输入，并释放已持有的键鼠；默认继续按序执行、如实记录迟到。该阈值不撤销已提交事件，也不能限制一次系统调用本身耗时。

`state=completed` 和 `accepted=true` 只证明输入提交完成，`effect_verified=false` 必须结合游戏状态、日志或录像验证。结果可能 `cancelled/unknown` 并含部分事件；失焦、进程退出、窗口变化或中断后会尝试释放本计划输入。不要自动重放失败的整段计划。远程超时意味着结果未知，此入口没有持久化动作查询或幂等重放；先观察游戏，不用新的请求盲目重试。

| 结果 | Agent 应如何继续 |
|---|---|
| completed，相关事件 accepted=true | 保存测量值，再核对游戏效果；允许报告抖动，不能承诺硬实时 |
| deadline_missed | 后续事件未提交；检查已返回事件和 cleanup，不能把中止样本算作完整测试 |
| unknown、accepted=null 或远程超时 | 可能已有部分输入；观察游戏与日志，不重放整段，不把会话 status 当作事件查询 |
| released=false | 输入释放未确认；停止追加输入，报告具体未确认释放的键鼠，不靠重跑计划恢复 |

同一批次的 `batch_inserted_count` 在各事件中重复出现，统计时按 `batch` 去重；部分提交没有逐事件身份，不据此猜测哪几个事件成功。

游戏内队列仍使用 [玩家流程](runtime-player.md) 的幂等 ID 与 status。其 `plan` 同样补齐 `at_ms`，步骤结果包含 `at_ms / started_ms / finished_ms`；分别记录计划开始、执行器开始调用和执行器确认完成的相对毫秒数，不是 Windows 输入时间或精确的原生动作完成时刻。
