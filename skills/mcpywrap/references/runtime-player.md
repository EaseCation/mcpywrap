# 玩家动作与连续计划

**仅限临时调试：严禁在任何业务代码中使用或依赖本页的 `mcpy.*`。** 它们只存在于已注入的调试会话，正常游戏运行时不存在；以下 Python 示例仅通过 `runtime py` 执行，不可复制到随游戏发布的脚本。业务实现须使用正式 ModSDK 或项目框架，完整边界见 [主 Skill](../SKILL.md#强制边界mcpy-仅限临时调试)。

统一安装：`mcpy --local --project <项目> runtime install --session <sid> --json`。远程换成 `--remote <endpoint>`。安装只在游戏内注入客户端函数，不要求控制服务器；UI、玩家层共享会话与输入互斥。当前内部客户端动作只对实测的 `3.10.0.420447` 开启，还会检查实际原生函数是否存在。

主 Skill 的方法表足以完成常规操作。CLI 名称把下划线换成连字符，例如 `runtime player select-slot 3`、`look-at 10.5 65.5 20.5`；所有 CLI 都带 `--session`，需要时加 `--json`。

## 一次提交吃东西和射箭

先通过 `runtime player snapshot` 确认快捷栏物品、饥饿值、箭数、位置和当前界面。以下例子假定**刚刚观察到**第 3 格是苹果，第 4 格是普通弓；实际任务必须替换为当前读到的槽位和瞄准方向。

```python
_result = mcpy.player.sequence([
    {"action": "select_slot", "slot": 3},
    {"action": "eat", "hold_ms": 2000,
     "expect": {"selected_slot": 3, "item": "minecraft:apple"}},
    {"action": "wait", "duration_ms": 200},
    {"action": "select_slot", "slot": 4},
    {"action": "look_at", "x": 10.5, "y": 65.5, "z": 20.5, "delay_ms": 100},
    {"action": "shoot", "hold_ms": 1200,
     "expect": {"item": "minecraft:bow"}}
])
```

也可把列表保存为调用端 UTF-8 JSON，执行：

```powershell
mcpy --local --project <项目> runtime player sequence --session <sid> --file <计划.json> --json
mcpy --local --project <项目> runtime player status --session <sid> --operation <返回id> --json
```

返回 `pending` 后，游戏会自行执行，不需 Agent 逐步驱动。按预计总时长稍后查询一次；仍未结束时再查询，避免高频轮询浪费 token。`index` 是已完成步骤数，`results` 按 1 起始的 step 编号保存每步状态；默认用 `changes` 只返回实际变化，省略重复状态，排查时加 `status --details`（Python 为 `status(id, details=True)`）。最后核对饥饿值、数量、目标或位置；`completed` 是动作流程完成，`effect_verified=false` 不保证所有服务端业务效果。

## 计划格式

- `action` 使用 Python 方法名：`move / look / look_at / select_slot / key / jump / sneak / attack / use_item / dig / eat / shoot`，或 `wait`。
- 参数同主 Skill 表。`wait` 只指定 `duration_ms`；每个步骤可加 `delay_ms`，表示在该步骤**开始前**等待。
- 队列中的 `attack / use_item / dig / eat / shoot` **不用填 snapshot**。控制层在执行到该步时重新观察并绑定快照，而不是复用提交计划时的旧目标。
- 可选 `expect` 支持 `selected_slot`、`item` 和 `target`。`target` 可指定 `type`、方块 `x/y/z` 或 `entityId`；例如 `{"target":{"type":"Block","x":10,"y":65,"z":20}}`。不符合断言时不执行该步，并停止后续步骤。
- 最多 32 步，计划时间合计最多 120 秒；单次输入持续 20–10000ms，单次等待/步骤前延迟 0–10000ms。不能嵌套队列或插入任意 Python。
- 操作之间有短暂的状态同步间隔。需要等待联机服务器或 Mod 的异步变化时显式加 wait/delay，不能假定低延迟环境的时间对所有服务器都适用。
- 队列执行期间拒绝新的玩家/UI 写操作；可查询状态和玩家快照。看向指定方向后会再次核对角度，若被其他控制逻辑改变则停止后续步骤，避免朝错误方向射箭。`runtime player stop` 停止本控制层的输入与队列，**不会退出游戏**；顶层 `mcpy stop` 才会结束游戏会话。

## 各动作的实际语义

玩家快照有效期 30 秒；瞬时动作也会使旧快照失效。普通单次调用示例：

```python
s = mcpy.player.snapshot()
_result = s
```

查看返回目标后，在下一次请求使用 `mcpy.player.attack(snapshot=s["snapshot"])` 等。不要复用前一次 UI 的 snapshot，也不要为远距离实体传入未观察到的 ID。

| 动作 | 边界与验证 |
|---|---|
| move | 按当前朝向锁定移动方向，限时自动解锁。方向向量由引擎归一化，不是速度；已有外部移动输入时拒绝接管。sprint=True 只适用于向前移动。 |
| look / look_at | 角度单位为度；look_at 接受世界中的具体点，瞄准方块中心通常用整数坐标 +0.5。完成后读 rotation/target 确认。 |
| key | 游戏内部按键，支持 SHIFT/CTRL/ALT、A–Z、0–9、SPACE、ENTER、ESC、F 键等引擎键名及 `+` 组合；遵循游戏当前键位。鼠标键码不能通过 key 伪装成攻击。 |
| select_slot | 槽位 1–9，直接切换快捷栏，不依赖数字键绑定。读 selected_slot/carried 确认。 |
| jump / sneak | 跳跃执行一次；潜行维持指定时间，结束恢复原状态。菜单打开时会释放持续动作。 |
| attack | 攻击准星瞄准、距离范围内的实体一次，走客户端真实攻击路径。方块使用 dig，不以挥手动画冒充造成伤害。 |
| dig | 使用当前工具挖掘准星方块，分步推进直到破坏、失去目标或达到时限；结束发送停止挖掘。`block_destroyed_reported` 是客户端报告，仍应核对服务器/后续快照。 |
| use_item | auto 在准星为方块时执行一次交互/放置，为空时对空使用。mode=air 强制对空使用，可用于食物、弓或穿戴等；hold_ms 只控制对空使用的持续时间，方块交互执行一次。实体喂食/交易尚未适配。 |
| eat | 必须是引擎识别的食物，默认 2000ms；读 hunger 和 carried.count 确认。已饱食、冷却、特殊食物或服务器规则可能阻止实际食用。 |
| shoot | 当前支持 `minecraft:bow`，默认蓄力 1200ms 再释放；应先确认箭和方向。读箭数及目标状态，必要时补后台画面。弩的装填/发射需要不同流程，目前明确拒绝。 |

食物/弓的原生开始接口可能返回 False 但已进入使用状态，封装已处理，Agent 不应自行重复调用原生 useItem。动作结束、取消或 UI 切换时会释放；游戏自身不执行 tick 时定时器不能及时推进，应查询状态并在需要时 stop。

## 失败处理

`stale_snapshot / out_of_reach / menu_open / wrong_item / unsupported_target` 表示条件不满足，先修正场景并重新观察。不要切前台或退回系统键鼠绕过错误。

单次动作和整个队列均可带 `request_id`，CLI 对应 `--request-id`。同一 ID 与参数只返回原操作，不重复输入；超时或 unknown 时通过 status 找回，不换新 ID 盲目重做。动作日志只保留最近 64 条；记录找不到不代表从未执行。队列失败保留已经完成的步骤，不自动回滚吃掉的物品或已经发射的箭。

批量动作失败时先读 `index / code / error / results`。不直接重跑整个计划；根据新快照决定是否执行剩余动作。需要卸载控制层时用 `runtime ui uninstall`，它会同时停止玩家队列并释放两层输入。
