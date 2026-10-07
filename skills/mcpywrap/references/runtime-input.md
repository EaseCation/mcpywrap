# 统一游戏输入：观察、计划、查询

CLI 0.4.2+；旧会话先重新runtime install。Windows特殊后端还需新worker；Mac旧运行包可能缺单调时钟，先查当前会话能力，不以版本或Skill更新宣称支持。

只有一份执行协议：`runtime input run --file` / `mcpy.input.run(plan)`。单键、组合、串行步骤与重叠输入都在同一 `steps` 列表中表达，无需选择 sequence/timeline。注入的 `mcpy.*` 仅供 runtime py 临时调试，禁止业务 Addon 依赖。

## 会话与发现

游戏加载后显式执行一次 `runtime install`，安装或更新 mcpy.input/UI/玩家适配；能力查询和观察不自动安装。

```text
mcpy --local --project <项目> runtime install --session <sid> --json
mcpy --local --project <项目> runtime input capabilities --session <sid> --json
mcpy --local --project <项目> runtime input observe --session <sid> --json
```

远程将全局路由改为 `--remote <Windows endpoint>`，文件仍在调用端读取。默认后端是游戏内 `game`，不抢系统焦点、不自动改用 Windows。

capabilities 的动作注册表包含每个动作的参数 schema、默认值、完成方式及 supported/reason；`keys` 是当前引擎可表达的键。不要仅按 CLI 版本推断运行包能力。未支持动作在整份计划预检时拒绝，不执行前面合法的步骤。

observe 默认在 HUD 返回玩家位置、方向、物品、准星目标及快照；菜单返回紧凑语义 UI 树、节点和快照。可显式使用 `--view player|ui`；UI 支持 `--query/--limit/--offset/--details`。快照中的有效目标、节点角色和 `allowed_actions` 帮助构造计划。HBUI 返回节点不可读的限制，可用键盘导航或后台截图观察，不猜测隐藏节点。

## 提交同一份计划

```json
{
  "schema_version": 1,
  "steps": [
    {"action": "key_down", "key": "W", "at_ms": 0},
    {"action": "player.attack", "at_ms": 200},
    {"action": "key_down", "key": "SPACE", "at_ms": 300},
    {"action": "key_up", "key": "SPACE", "at_ms": 450},
    {"action": "key_up", "key": "W", "at_ms": 600}
  ]
}
```

```text
mcpy --local --project <项目> runtime input run --session <sid> --file <plan.json> --request-id <32位小写hex> --json
mcpy --local --project <项目> runtime input status --session <sid> --operation <operation_id> --details --json
mcpy --local --project <项目> runtime input cancel --session <sid> --operation <operation_id> --json
mcpy --local --project <项目> runtime input stop --session <sid> --json
```

`operation_id` 标识输入操作；调用方 `request_id` 用于幂等，当前与 operation_id 同值。传输请求 ID 单独放在 `transport.request_id`，不能用它查询输入操作。未传 request_id 会生成并返回；超时返回原 ID，查询结果，不换新 ID 盲目重发。同 ID 与相同规范化计划返回原操作，不同计划拒绝。历史保留最近64条，找不到不证明从未执行。

默认 status 是摘要；details 返回规范化计划、每步实际开始/结束、输入事件和清理事件。完成/接受仍保留 effect_verified=false；实际运动、伤害、消费或 UI 更新需观察核对。

## 动作与时间规则

常用参数示例；完整字段由 capabilities 的同一注册表给出：

| 动作 | 参数 | 完成语义 |
|---|---|---|
| key | `keys:["CTRL","W"]`, `duration_ms:500` | 依数组顺序按下，实际保持时长后逆序释放，再推进 |
| key_down/key_up | `key:"W"` | 一个边沿提交后继续，键由整个计划持有；必须配对 |
| wait | `duration_ms:100` | 实际执行到该步骤后等待 |
| player.move | forward/right、sprint、duration_ms | 移动向量锁定，完成释放确认；不能与已持有方向键接管同一输入 |
| player.look/look_at | pitch/yaw 或 x/y/z | 修改并核对朝向；不是原始鼠标移动 |
| player.select_slot | `slot:1`（1–9） | 选槽；不是数字键或滚轮事件 |
| player.jump/sneak | jump无持续参数；sneak有duration_ms | 语义跳跃或潜行状态动作；不是SPACE/SHIFT边沿 |
| player.attack/dig | attack瞬时；dig有duration_ms | 每步重新观察准星与距离，通过真实客户端动作路径 |
| player.use_item/eat/shoot | mode与duration_ms | 保留目标/物品守卫及实际使用/释放流程 |
| ui.click/slide | node、snapshot；click可带keys；slide用fraction | 单个当前快照的节点交互；按角色预检，自动抬起 |
| ui.scroll | node、snapshot、percent | 设置滚动容器百分比；不是原始滚轮边沿 |
| ui.set_control_value | node、snapshot、value | 仅控件赋值，不声称键入、IME或提交 |
| pointer.down/up/move/relative/wheel | button，x/y，dx/dy或delta | 原始设备输入，首版仅显式windows-sendinput后端 |

统一字段为 `action/at_ms/delay_ms/duration_ms`。JSON 组合必须是有序数组；只在人工快捷命令中允许 `CTRL+W` 字符串：

```text
mcpy runtime input key "CTRL+W" --duration-ms 500 --session <sid> --json
```

它生成与 `{"action":"key","keys":["CTRL","W"],"duration_ms":500}` 相同的计划，调用同一个run。新入口不自动修饰键排序，`["W","CTRL"]` 保持不同提交顺序。同一时刻的步骤严格按列表，不宣称原子输入。

排时遵循已有计划语义：省略at_ms时，取前一步**计划结束**加delay_ms（默认0）；显式at_ms不能早于前一步计划结束，二者同一步互斥。规范化后只有at_ms，没有运行时重新追加delay_ms。每个动作的duration_ms参与计划预留；瞬时边沿名义时长为0，持键区间不阻止其他边沿或语义步骤。

实际执行到某一步要同时满足计划时刻与前一步完成约束。完成型key持续时间从实际按下后计算；wait从实际执行时计算。前步迟到可以抵消计划空隙，不能用delay_ms保证实际停顿；需要实际等待就插入wait。前步提前完成仍等后步计划时刻。原始key_down/up的迟到可能压缩持键时长，记录实际时间，不偷偷延长。

默认后端game，起点为首次可用客户端调度点，使用经过确认的单调毫秒时钟；没有tick模式，不将30Hz脚本回调、渲染帧与AuthInput tick换算。默认 `max_lateness_ms:null` 迟到继续；显式设置非负整数则超限中止。

## 目标、界面与清理

玩家步骤可以带 `expect:{"selected_slot":1,"item":"minecraft:bow","target":{"type":"Entity","entityId":"..."}}`。执行到每一步重新观察并断言；攻击和物品动作自动绑定当前快照，不提交陈旧观察对象。

首版每份 UI 计划只有一个 ui.* 节点动作，绑定刚取得的node/snapshot；页面改变后再observe，不支持跨页选择器/条件脚本。ui.click可带通用CTRL/SHIFT/ALT修饰键，按数组顺序按下，节点动作完成后逆序释放。页面变化是该单个UI交互的允许结果；普通键盘/玩家计划遇到页面变化停止后续步骤并清理输入，包括打开聊天/菜单的键。菜单当前页面的键盘操作允许，player.*仍只允许HUD。

所有新计划独占一个会话写操作，等待期间也保持busy；允许observe/status。旧游戏内写入口共享互斥，不绕过新计划。人工持键归属不能可靠识别，应在专用无人同时操作的会话验收。

取消、失败、世界/界面失效、卸载和超时都尝试释放子动作及本计划持有输入。可能已按下但抛错的键也登记清理责任。释放失败返回unknown、unconfirmed_release_keys并保持busy；修复条件后用stop重试，不能重放计划。stop不会退出游戏，顶层mcpy stop才结束会话。

首版限制：最多256步、120秒计划、125秒执行上限、规范化JSON16KiB。单个game持续动作20–10000ms、wait0–10000ms。计划结束必须配对所有边沿，重复持有同一键拒绝。日志总预算64KiB，丢失由logs_truncated及每类dropped计数报告，不能把不完整日志算作精确验证通过。

游戏不推进或调试通道不能处理命令时，查询/取消/释放可能延后；返回unknown/unavailable，不宣称当场已释放。恢复回调先检查墙钟上限，不补发过期操作。Windows worker的cancel/stop可能先返回cancel_requested；继续查询原操作到终态，不把请求接受当作清理已完成。

## Windows 特殊后端与 macOS

需要原始设备路径时显式在计划顶层设置 `"backend":"windows-sendinput"`。同一个run/status/cancel协议；实际执行器由目标会话worker持有，远程不在调用端操作设备。支持key、边沿、wait及pointer.*；不执行player.*或ui.*语义动作。

原始指针计划提供width/height参考客户区；坐标移动、滚轮及点击核验窗口尺寸和焦点/遮挡。VK/SC/E0、明确左右/扩展键仅在能保留语义的设备后端使用。普通game中不把RCTRL悄悄映射CTRL、不把NUMPAD_ENTER悄悄映射ENTER。常用规范名及旧别名集中映射，具体支持键以capabilities为准。

Windows特殊后端会激活并占用游戏前台。统一调度器记录SendInput调用边界；不承诺0–20ms硬实时或游戏消费间隔。旧顶层input-sequence仍保持原有批量提交与调度行为，见[兼容输入参考](input-writing.md)。

macOS Apple Silicon使用同一游戏协议，但Python2原生运行包必须提供 `_mcpy_launcher.monotonic()` 或其他已确认单调时钟。旧包缺时钟返回missing_monotonic_clock；不自动下载、改包或退回CPU/墙上时间。原生适配源码与限制见仓库 `native/runtime_input/README.md`。Mac未实机验收前不宣称完整支持；pointer/text缺能力仍明确拒绝。

## Python 与兼容入口

临时客户端Python对应：

```python
observation = mcpy.input.observe()
operation = mcpy.input.run(plan, request_id=request_id)
result = mcpy.input.status(operation['operation_id'], details=True)
```

`mcpy.input.key(keys, duration_ms=80)`只生成并运行计划。Windows设备后端由宿主worker控制，Python游戏内方法明确拒绝该后端；公开CLI保持同一JSON协议。

旧 runtime player/ui、顶层key/mouse/input-sequence及mcpy.player/ui方法仍可调用，从默认帮助隐藏，并保留原参数、时间起点、修饰键优先顺序、历史与后端语义。不要把旧timeline的at、桌面type字段写进新steps。迁移参考见[按键兼容对照](input-writing.md)。

## 常见混淆的判定

| 容易混淆的内容 | 新协议规则 |
|---|---|
| 顶层列表、events、type、at、clock、hold_ms | 均不是新计划字段；顶层对象使用schema_version/steps，步骤使用action/at_ms/delay_ms/duration_ms |
| JSON `keys:"CTRL+W"` | 不接受；写有序数组 `["CTRL","W"]`。只有CLI快捷key或Python快捷key允许组合字符串 |
| 相同组合的两种顺序 | `["W","CTRL"]`与`["CTRL","W"]`会提交不同顺序；不能按旧key规则自动修饰键优先 |
| `delay_ms:100`和wait 100 | delay在计划表留空隙，可能被迟到抵消；wait从实际执行时开始等待 |
| key持续时长和down/up间隔 | 完成型key按实际执行保持时长；绝对边沿迟到可能压缩区间，不能互换来“修复”样本 |
| `session`、UI `snapshot`、`operation_id` | 分别用于会话路由、节点校验、操作查询。输入request_id可找回同一operation；transport.request_id不能用于input status |
| key_up和停止潜行/疾跑 | 按键释放不证明姿态改变，需新观察或服务端证据；不能直接修改玩家状态冒充键盘消费 |
| player.look/select_slot/attack与pointer事件 | 前者是游戏语义动作，后者是设备路径；结果中的input_path说明实际路径，不自动替换 |
| completed/accepted与业务完成 | 仅证明控制流程或提交阶段；保持effect_verified=false，核对位置、物品、伤害或UI结果 |
| unknown/busy/operation_not_found | 查原ID和清理状态，不换ID重跑；记录淘汰不证明未执行；释放未知期间不追加写操作 |
