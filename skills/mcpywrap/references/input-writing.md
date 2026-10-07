# 按键操作写法与兼容对照

本页为旧入口兼容参考。日常新任务统一使用 [runtime input](runtime-input.md)；旧行为仍保留，不自动更换后端。

本页按当前代码解析规则整理。游戏内入口最终按会话中的网易 KeyBoardType 与输入 API 能力执行；文档中的键表不代替目标会话能力或实际效果验证。`mcpy.*` 只用于 runtime py 临时调试，不写入业务 Addon。

## 入口选择

| 入口 | 键参数写法 | 组合/顺序 | 持续时间与编排 | 执行与查询 |
|---|---|---|---|---|
| `runtime player key` / `mcpy.player.key()` | 一个字符串 `"CTRL+W"` | 最多 8 个不同键；码 16/17/18 的修饰键先按，其他键保留相对次序；逆序释放 | hold_ms，默认 80，20–10000ms；全组同时持有 | 游戏内后台；先 runtime install；幂等 id、status/cancel/stop |
| `runtime player sequence` / `mcpy.player.sequence()` 中的 key | `{"action":"key","keys":"W+A+SPACE","hold_ms":200}` | 每步使用上述 key 规则；前步完成并释放后执行下一步 | 每步 at_ms 或 delay_ms；最多 32 步，计划 120 秒 | 游戏内后台；同一队列占有写权限；幂等与状态查询 |
| `runtime player timeline` / `mcpy.player.timeline()` | `{"at":0,"action":"key_down","key":"W"}` | 单事件单键；允许重叠；全部边沿严格按列表顺序，包括同一时刻；正常 up 按列表，异常清理按实际 down 逆序 | 明确 at，单调毫秒；最多 256 事件/120 秒；默认迟到继续 | 游戏内后台；现有会话重新 install 后查询 timeline 能力；幂等与状态查询 |
| 顶层 `key` | 多个 CLI 参数 `CTRL W`，或 `"CTRL+W"`，或混合 `"W+A" SHIFT` | 命名/VK 修饰键优先；扫描码保持相对顺序；最后逆序释放 | --hold-ms，默认 80，20–60000ms；同一组合整体持有 | Windows SendInput，会激活游戏；无需注入；无玩家 operation 查询 |
| 顶层 `input-sequence` | `{"type":"key_down","key":"W","at_ms":0}` | 单事件单键；允许重叠；严格列表顺序；相邻同刻键/按钮事件可合为一次 SendInput | at_ms 或 delay_ms；最多 256 事件/10 秒，JSON 64 KiB；默认迟到继续 | Windows 前台；无需注入；返回提交日志，无持久化幂等或操作查询 |
| 顶层 `mouse ... --keys` | `--keys SHIFT`，`--keys "CTRL+ALT"` 或重复 --keys | 仅修饰键，按键解析后不允许普通键；鼠标动作结束后释放 | --duration-ms，默认 80，20–60000ms | Windows 前台；键与鼠标动作组合，无玩家 operation 查询 |

前三种使用同一游戏内部键盘接口。后三种使用 Windows 桌面输入，不能当作前三种的无差别替代。所有入口的接受/提交成功都不等于实际移动、跳跃或服务端已经消费输入；目前没有模拟 tick 精确对齐。

## 游戏内键名：key、sequence、timeline 共用

大小写不敏感，键名周围可有空格；每个键可带 `KEY_` 前缀。因此 `w`、`W`、`KEY_W` 等价，`key("key_ctrl + key_w")` 也是组合写法。timeline 每个事件仍只能填一个键。

代码明确提供的别名只有以下五组：

| 简写 | 查询的网易枚举 |
|---|---|
| CTRL | KEY_CONTROL |
| SHIFT | KEY_LSHIFT |
| ALT | KEY_MENU |
| ENTER | KEY_RETURN |
| ESC | KEY_ESCAPE |

原枚举名也可直接写，例如 CONTROL、LSHIFT、MENU、RETURN、ESCAPE。`CTRL+CONTROL` 属于同一键重复，拒绝；timeline 可以 `CTRL` down 后用 `CONTROL` up，按键码配对。

除上述别名外，解析器查找 `KEY_<输入名称>`，要求枚举值是整数且在 1–255。因此可接受的完整集合随当前引擎枚举而定。以下是 [网易正式文档 KeyBoardType](https://mc.163.com/dev/mcmanual/mc-dev/mcdocs/1-ModAPI/枚举值/KeyBoardType.html?catalog=1) 列出的有效键名，均可再加 KEY_ 前缀：

| 类别 | 游戏内写法 |
|---|---|
| 字母、顶部数字 | A–Z、0–9 |
| 编辑/基本键 | BACKSPACE、TAB、RETURN / ENTER、PAUSE、ESCAPE / ESC、SPACE |
| 修饰键 | LSHIFT / SHIFT、CONTROL / CTRL、MENU / ALT |
| 导航 | PG_UP、PG_DOWN、END、HOME、LEFT、UP、RIGHT、DOWN、INSERT、DELETE |
| 锁定键 | CAPS_LOCK、NUM_LOCK、SCROLL |
| 小键盘 | NUMPAD0–NUMPAD9、MULTIPLY、ADD、SUBTRACT、DECIMAL、DIVIDE |
| 功能键 | F1–F13；更高编号只有实际引擎枚举包含时才可用 |
| 标点物理键 | SEMICOLON、EQUALS、COMMA、MINUS、PERIOD、SLASH、GRAVE、LBRACKET、BACKSLASH、RBRACKET、APOSTRAPHE |
| 遗留键 | GOBACK 的码 4 可被解析器接受，但官方标记为已弃用，不作为回归测试配方 |

`APOSTRAPHE` 是官方枚举的原拼写，不能自行更正成 APOSTROPHE。官方表没有 RSHIFT/LCTRL/RCTRL/LALT/RALT、NUMPAD_ENTER、Windows 媒体/浏览器键；只有实际引擎增添对应 KEY_ 枚举时才可能支持，不能沿用桌面支持范围来推断。

游戏内不接受 `VK:0x57`、`SC:0x11`、`E0:0x1D`、直接整数键码或鼠标负键码。鼠标键名经过大写转换也不会变成受支持输入。攻击/使用物品走 player attack/use-item 等独立动作。

这些是物理键操作，不是文本输入：`EQUALS` 是等号/加号所在键，输入加号字符需要 SHIFT 与 EQUALS 的组合；大写字母也受 SHIFT/CAPS_LOCK 影响。SHIFT/CTRL 的姿态结果还受键位与保持/切换设置影响。

## Windows 桌面键名：key、input-sequence 共用

大小写不敏感，忽略键名两侧空格；不支持通用 KEY_ 前缀。桌面解析器支持以下全部命名键（冒号代码格式另见下一节）：

| 类别 | 正式键名 |
|---|---|
| 字母、顶部数字 | A–Z、0–9 |
| 基本键 | ESC、ESCAPE、ENTER、TAB、SPACE、BACKSPACE、CLEAR、PAUSE、CAPSLOCK |
| 导航 | PAGEUP、PAGEDOWN、END、HOME、UP、DOWN、LEFT、RIGHT、INSERT、DELETE |
| 其他编辑键 | SELECT、PRINT、EXECUTE、PRINTSCREEN、HELP |
| 修饰/系统键 | LSHIFT、RSHIFT、LCTRL、RCTRL、LALT、RALT、LWIN、RWIN、APPS、SLEEP |
| 功能键 | F1–F24 |
| 小键盘 | NUMPAD0–NUMPAD9、NUMPAD_ENTER、MULTIPLY、ADD、SEPARATOR、SUBTRACT、DECIMAL、DIVIDE、NUMLOCK、SCROLLLOCK |
| 输入法键 | KANA、IME_ON、JUNJA、FINAL、KANJI、IME_OFF、CONVERT、NONCONVERT、ACCEPT、MODECHANGE |
| 浏览器键 | BROWSER_BACK、BROWSER_FORWARD、BROWSER_REFRESH、BROWSER_STOP、BROWSER_SEARCH、BROWSER_FAVORITES、BROWSER_HOME |
| 音量/媒体键 | VOLUME_MUTE、VOLUME_DOWN、VOLUME_UP、MEDIA_NEXT、MEDIA_PREV、MEDIA_STOP、MEDIA_PLAY_PAUSE |
| 启动键 | LAUNCH_MAIL、LAUNCH_MEDIA、LAUNCH_APP1、LAUNCH_APP2 |
| OEM 标点键 | OEM_1、OEM_PLUS、OEM_COMMA、OEM_MINUS、OEM_PERIOD、OEM_2、OEM_3、OEM_4、OEM_5、OEM_6、OEM_7、OEM_8、OEM_102 |
| 其他键 | PROCESSKEY、ATTN、CRSEL、EXSEL、EREOF、PLAY、ZOOM、PA1、OEM_CLEAR |

完整兼容别名：

| 别名 | 解析为 |
|---|---|
| SHIFT、CTRL / CONTROL、ALT、WIN | LSHIFT、LCTRL、LALT、LWIN |
| RETURN、PGUP、PGDN、INS、DEL、BACK、PRTSC | ENTER、PAGEUP、PAGEDOWN、INSERT、DELETE、BACKSPACE、PRINTSCREEN |
| NUMPAD_ADD、NUMPAD_SUBTRACT、NUMPAD_MULTIPLY、NUMPAD_DIVIDE、NUMPAD_DECIMAL | ADD、SUBTRACT、MULTIPLY、DIVIDE、DECIMAL |
| SEMICOLON、EQUALS / PLUS、COMMA、MINUS、PERIOD | OEM_1、OEM_PLUS、OEM_COMMA、OEM_MINUS、OEM_PERIOD |
| SLASH、BACKTICK、LBRACKET、BACKSLASH、RBRACKET、QUOTE | OEM_2、OEM_3、OEM_4、OEM_5、OEM_6、OEM_7 |

`NUMPAD_ENTER` 带扩展标记，普通 ENTER 不带；不是两个名称指向完全相同的事件。`PLUS` 只表示 OEM_PLUS 所在键，不会自动附加 SHIFT。OEM 标点实际字符受键盘布局影响。

支持列表说明解析和 SendInput 编码能力，不保证所有系统键、IME 或媒体键都被 Minecraft 消费。

## VK、扫描码与组合字符串

这些格式仅用于 Windows 桌面 key/input-sequence：

| 格式 | 示例 | 规则 |
|---|---|---|
| 虚拟键 | `VK:0x57` 或 `VK:87` | 范围 0x08–0xFE，排除 VK_PACKET 0xE7 和鼠标键；不是 Unicode 输入接口 |
| 普通扫描码 | `SC:0x11` 或 `SC:17` | 1–0x7F 的按下码；工具负责生成释放标记 |
| 扩展扫描码 | `E0:0x1D` 或 `E0:29` | 同一扫描码范围，额外带 E0 扩展标记 |

数字按 Python `int(number, 0)` 解析；十六进制需要 0x 前缀。推荐十六进制或无前导零的十进制，不能把 `SC:11` 当作十六进制 0x11。扩展标记 E0 与按键释放无关。

桌面单次 key 可以混合：

```text
mcpy key --session <sid> CTRL W --hold-ms 500 --json
mcpy key --session <sid> "CTRL+W" --hold-ms 500 --json
mcpy key --session <sid> "W+A" SHIFT --hold-ms 500 --json
mcpy key --session <sid> "E0:0x1D+SC:0x11" --hold-ms 500 --json
```

前三个是同一请求内的组合，不是依次敲击。命名修饰键及对应 VK 会自动排到前面；SC/E0 没有 vk，保持扫描码之间的列表次序，要自行把扫描码修饰键写在前面。重复键或重复别名（例如 CTRL+LCTRL）、空项 W++A 都拒绝。

input-sequence 的每个事件只能有一个键，拒绝 `"CTRL+W"`。同一键的 down/up 应使用同一种表示；执行器会检查并拒绝能解析到同一身份却混用 VK/扫描码/别名的计划，不建议利用不同表示绕过持键检查。

mouse 的 --keys 使用同一解析器，但会再限制为修饰键 vk：SHIFT/CTRL/ALT/WIN 与它们的左右变体可用；对应修饰键 VK 格式也可通过校验。普通 W、SC/E0 格式不允许。修饰键按整个鼠标操作保持；需要独立释放或键鼠交叠用 input-sequence。

## 跨模式容易写错的键名

| 目的 | 游戏内 key/sequence/timeline | Windows key/input-sequence |
|---|---|---|
| 常用移动/跳跃/修饰 | W/A/S/D、SPACE、SHIFT、CTRL、ALT | 同名可用；SHIFT/CTRL/ALT 解析为明确的左侧 Windows 键 |
| Caps Lock | CAPS_LOCK | CAPSLOCK |
| Page Up/Down | PG_UP / PG_DOWN | PAGEUP / PAGEDOWN，或 PGUP / PGDN |
| Num Lock | NUM_LOCK | NUMLOCK |
| Scroll Lock | SCROLL | SCROLLLOCK |
| 反引号键 | GRAVE | BACKTICK / OEM_3 |
| 单引号键 | APOSTRAPHE | QUOTE / OEM_7 |
| 等号所在键 | EQUALS | EQUALS / PLUS / OEM_PLUS |
| 左 Ctrl | CTRL / CONTROL，官方码 17 | CTRL / CONTROL / LCTRL，码 0xA2 |
| 左 Shift | SHIFT / LSHIFT，官方码 16 | SHIFT / LSHIFT，码 0xA0 |
| Alt | ALT / MENU，官方码 18 | ALT / LALT，码 0xA4；MENU 不是桌面别名 |
| 前缀 | KEY_W 等可用 | KEY_W 不支持 |
| F 键 | 官方表 F1–F13，实际枚举决定 | F1–F24 |

## 后台入口示例

游戏内单次组合使用一个字符串，不支持 `runtime player key CTRL W` 的多个位置参数：

```text
mcpy runtime player key "W+A+SPACE" --session <sid> --hold-ms 500 --json
```

Python 临时调用等价于 `mcpy.player.key("W+A+SPACE", hold_ms=500, request_id=<id>)`。

串行队列 JSON（文件为列表）：

```json
[
  {"action": "key", "keys": "W+A+SPACE", "hold_ms": 200},
  {"action": "key", "keys": "W", "hold_ms": 500, "delay_ms": 100}
]
```

```text
mcpy runtime player sequence --session <sid> --file <steps.json> --json
```

第一步释放整个组合，第二步重新按 W；两步之间不会持续保持 W。Python 用 `mcpy.player.sequence(steps, request_id=<id>)`。

后台重叠时间线 JSON（文件为对象）：

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
mcpy runtime player timeline --session <sid> --file <plan.json> --request-id <id> --json
mcpy runtime player status --session <sid> --operation <id> --details --json
mcpy runtime player cancel --session <sid> --operation <id> --json
```

W 持续一秒，SPACE 独立按放；Python 用 `mcpy.player.timeline(plan, request_id=<id>)`。同一时刻将 W、CTRL 以相反顺序列出，会保留两种不同的提交顺序。详见 [后台按键时间线](runtime-key-timeline.md)。

## 桌面时间线与鼠标修饰键示例

Windows input-sequence JSON（文件为列表，字段 type/at_ms 不同于后台时间线）：

```json
[
  {"type": "key_down", "key": "W", "at_ms": 0},
  {"type": "key_down", "key": "SPACE", "at_ms": 300},
  {"type": "key_up", "key": "SPACE", "at_ms": 450},
  {"type": "key_up", "key": "W", "at_ms": 1000}
]
```

```text
mcpy input-sequence --session <sid> --file <events.json> --json
mcpy mouse click-current --session <sid> --width 1280 --height 720 --button right --keys "CTRL+SHIFT" --json
mcpy mouse click-current --session <sid> --width 1280 --height 720 --button right --keys CTRL --keys SHIFT --json
```

两种 mouse 写法等价。鼠标按钮使用 --button left/right/middle 或 input-sequence 的 mouse_down/mouse_up；不能写到键名参数里。含鼠标的 input-sequence 必须指定参考客户区 --width/--height，click-current 不移动鼠标但需验证指针位置。详见 [连续动作编排](input-sequence.md)。

## 本地、远程与平台兼容

- 本地全局参数：`mcpy --local --project <项目> --non-interactive <命令>`。远程：`mcpy --remote <endpoint> --project <调用端项目> --non-interactive <命令>`。全局路由参数放在子命令之前；执行端决定输入能力，调用端操作系统不决定远端能力。
- Windows 本机与远程的游戏内 key/sequence/timeline 均走目标客户端内部输入；文件在调用端读取。不自动回退到桌面输入。
- Apple Silicon macOS 本地 key/sequence 按当前运行包的引擎能力使用。timeline 还要求经过确认的单调时钟；Python 2 macOS 的 time.clock 是 CPU 时间，当前不作为可用回退，缺少 time.monotonic 则不支持。首批 timeline 实机验证为 Windows 3.9.0.401155、3.10.0.420447。
- Windows key/input-sequence/mouse 要求目标 Windows 会话并占用前台；Apple Silicon macOS 本地不提供这些桌面入口，但可通过 remote 操作 Windows 执行端。
- 新 timeline 需包含此次实现的 CLI 和重新 runtime install；版本号本身不足以判断，因为开发 checkout 仍可能显示 0.4.1。以实际 --help 与 player status 能力为准。
- Skill 兼容脚本 game_window.py 的 key/mouse 是顶层桌面命令透传，不是游戏内 player key。它不提供 timeline 或 input-sequence 的 action 名，使用公共 CLI 对应入口即可。

player move（LockInputVector）、jump（SimulateJump）、sneak（状态切换）、select-slot（直接选槽）是游戏语义动作，不能等同于 W/SPACE/SHIFT/数字键事件。回归复现需要键盘边沿时使用 key 或 timeline，并记录实际后端。
