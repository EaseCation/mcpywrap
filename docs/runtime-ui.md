# 游戏内 UI 自动化

严禁业务代码依赖 `mcpy.*`：这些方法仅存在于临时注入的调试会话，正常游戏运行环境不提供它们；业务实现须使用正式 ModSDK 或项目框架。

`mcpy runtime ui install` 通过现有 Safaia 客户端 Python 通道注入控制层，提供 `mcpy.ui` 与原始客户端 ModSDK 简写 `mcpy.api`。本地和远程调用共用这个通道，不需要安装行为包，不向 Windows 桌面发送键鼠事件。

```powershell
mcpy --local --project D:\mods\demo runtime ui install --session <sid> --json
mcpy --local --project D:\mods\demo runtime ui snapshot --session <sid> --json
mcpy --local --project D:\mods\demo runtime ui click <node> --snapshot <snapshot> --session <sid> --json
mcpy --local --project D:\mods\demo runtime ui snapshot --session <sid> --json
```

操作方式、Python 简写、分页、失败恢复及能力边界见随包维护的 [Skill 操作说明](../skills/mcpywrap/references/runtime-ui.md)。需要补图时，`screenshot --background-only` 可保证捕获失败不回退到前台；旧版远端不接受该选项时会返回错误。

## 接口契约

| Python 方法 | CLI | 语义 |
|---|---|---|
| `snapshot(root=None, query=None, include_offscreen=False, limit=80, offset=0, details=False)` | `runtime ui snapshot` | 当前界面的有界文字树；生成新 snapshot 和该次返回节点的 id |
| `click(node, snapshot, request_id=None)` | `click <node> --snapshot ...` | 按节点可见范围发送游戏内触控，自动抬起 |
| `slide(node, fraction, snapshot, request_id=None)` | `slide <node> --fraction ...` | 在滑轨比例位置交互；业务值以刷新结果为准 |
| `scroll(node, percent, snapshot, request_id=None)` | `scroll <node> --percent ...` | ModSDK 直接滚动容器，百分比 0–100 |
| `set_control_value(node, value, snapshot, request_id=None)` | `set-control-value <node> --value <JSON>` | 控件状态写入，不承诺业务回调或提交 |
| `status(operation=None)` | `status [--operation ...]` | 查询能力、当前动作或最近记录 |
| `cancel(operation)` | `cancel --operation ...` | 抬起正在执行的动作，不重复已完成动作 |
| `close()` | `uninstall` | 释放并解绑事件；保留游戏会话 |

CLI 将业务错误提升为 `ok=false` 和非零退出码。`runtime_state=completed` 只表示 Python 脚本返回；`state=pending/completed/failed/unknown/cancelled` 是动作状态，`effect_verified` 始终要求调用方用新观察或业务状态验证。`set-control-value` 特别标记 `verification=control_only`。

对直接 Python 使用者，方法在无效参数、过期快照等情况下抛出 `UIError`，其 `code` 给出稳定错误类型；`dispatch` 是 CLI 使用的结构化异常包装。

## 可靠性机制

快照的 `tree_format=semantic-v1` 表示浅层语义树：顶部是实际界面标题，其下最多两层区域/小组，控件最多三级缩进。滚动容器保留操作编号，字段标题与值合并，纯布局节点不直接输出；区域内标题结合结构范围和位置划分后续内容。没有足够证据时保留平铺，不强行猜测分组。

`nodes` 保留原有操作字段，并增加 `parent / depth / group / presentation`；`groups` 的 `id / parent / depth` 构成分组关系，`node_id` 仅在该组对应的真实标题或滚动节点被本页返回时提供。筛选和分页补齐的祖先组标记 `context_only`，不伪造可操作 ID。`--query` 同时匹配分组名称和只读字段值，`--details` 可查看合并字段的 `related_paths`。展示结构在原始快照签名计算之后生成，不修改用于输入校验的原始记录。

- 每次输入前重新扫描并比较页面/tab、生命周期代数、尺寸、路径、文字、值和布局。仅接受当前快照已返回的节点，快照有效期 120 秒，一次动作后失效。
- 使用 Push/Pop/尺寸变化等引擎事件，使关闭后重新打开的同名页面也无法复用旧编号。重复 install 不重复监听；升级保留 Python 2 模块对象，避免事件方法的 globals 被模块回收清空。
- 快照按祖先可见性裁剪，剪裁框传递到后代。重复路径只输出为 ambiguous，不允许动作。完整重叠命中与所有 disabled 绑定尚无法读取，节点会明确给出 unknown/限制，不声明所有控件均可点击。
- 按下前安排 80ms 后的游戏内自动抬起；调用端失联不会依赖下一条请求释放。游戏本身暂停执行脚本/卡死时无法保证定时器及时运行，应查询状态。释放失败保留活动动作，阻止新输入和卸载，允许 cancel 再次释放。
- 动作可指定幂等 request-id，最近 64 条动作保留结果；相同参数不重复发送，冲突参数拒绝。不因 unknown 自动重试。
- 文字、值和输出大小受限，快照分页显式给出 `truncated / next_offset`。树大小限制 40000 个遍历节点、深度 100；失败提示缩小 root。

## 兼容性与边界

读取类型与内部触控依赖网易引擎的私有 `gui` 接口。0.3.18 起不按版本号阻止调用，按实际接口与生命周期监听报告能力；缺失或调用异常返回 `engine / compatibility_hint`，提示可能存在版本兼容性差异，不退回 SendInput。接口存在不等于业务效果已验证。

HBUI/HTML 页面暂不提供节点访问：`snapshot` 与节点操作返回 `unsupported_ui`，不暴露其底层 JSON UI 控件。3.9 的新版音频页属于这种情况，可用严格后台截图观察。

初版不提供通用文字键入、IME、拖拽或手柄输入；可用 `set-control-value` 修改输入框显示，但不能宣称已提交。锁屏、最小化、虚拟桌面、用户键鼠对后台游戏的反向隔离没有完成验收。

`snapshot` 的 root 默认为标准原生界面根或 `/main`。其他自定义界面可显式指定真实子树；不支持的结构会返回错误。标准滚动接口需要外层 scrolling_panel，而 Toggle 直接绑定原生节点时使用空相对路径；这些适配由控制层处理。

## 验证

单元与回环 HTTP 测试在 `tests/test_runtime_ui.py`：注入源直接执行、重复安装和升级、远程同名命令路由、过期/变化快照、重复路径、屏外节点、重复请求、按下失败、自动抬起、释放失败、文本参数转义和控件状态语义。

`tests/test_runtime_ui_outline.py` 覆盖语义层级深度、不同卡片/列隔离、重复标签合并、只读字段、跨页上下文、原始签名不变与分组后的实际点击定位。

2026-10-03 在引擎 `3.10.0.420447` 上完成 [实机验收](validation/runtime-ui.json)：真实设置页扫描 1222 个原始节点后输出 29 个语义节点，用时 65ms；导航中的“世界 / 控制 / 通用”与右侧“游戏设置 / 世界首选项”分别成组。[文字树样例](validation/ui-tree.txt) 保存了设置页、筛选分页和暂停菜单的实际输出。

20 次公开 CLI 调用验证安装、滚动及恢复、点击音频页、主音量 25 → 恢复、旧快照拒绝与重复请求。约 10ms 间隔采样未发现前台窗口或光标变化。记录中的源码摘要标识当次实测版本；当前发布仍须运行自动化回归与发布检查，不把模拟测试或历史记录当作新引擎的验收。

0.3.17 发布前使用清理后的注入源重新完成 26 次后台 CLI 回归，采样未记录前台窗口或光标变化，测试会话已关闭。全量自动化 378 项结果 OK（5 项按环境跳过），另行启用桌面原生验收的 5 项全部通过；源码摘要和结果保存在同一验收记录的 `release_regression`。

0.3.18 在 `3.9.0.350466` 与 `3.9.0.401155` 的正式封装实测见 [3.9 验收记录](validation/runtime-3.9.json)：无需临时放行版本，原生 UI、玩家动作与挖掘后的连续队列通过，HBUI 页面明确拒绝节点访问；测试会话已停止。
