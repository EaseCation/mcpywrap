# 遇到问题时再读

| 现象 | 下一步 |
|---|---|
| 没有 `--project` 或 `status` | 当前 CLI 版本缺少能力；选择支持此 Skill 的版本或源码提交重新安装，不猜测参数。 |
| uv 报 Python 版本链接失效 | bootstrap 可用 `-Python <现有 python.exe 的绝对路径>`，避免依赖失效的次版本链接。 |
| `init` 拒绝已有配置 | 直接使用现有项目，必要时执行 `sync`；不要删除配置来绕过保护。 |
| 本地依赖结构无效 | 检查引用是否为 Addon 根目录，是否包含有 manifest 的行为包或资源包。 |
| Python 依赖未安装 | 按错误提示执行明确的 `add "requirement"`。本地目录引用不会自动安装其包依赖。 |
| 游戏或皮肤未找到 | 查看 `doctor --json`；指定正确下载目录或先在 MC Studio 下载所需引擎资源。 |
| 指定版本不存在 | 从 doctor 的候选中选择用户认可的完整版本，不静默升级。 |
| 游戏启动失败或超时 | 查看会话状态、`worker.log`、SDK 的 `game.log` 和引擎的 `engine.log`；避免无依据重复启动。 |
| PID 身份不匹配 | 不终止该进程；会话可能过期，重新确认目标。 |
| 运行正常但没有加载证据 | 查找项目日志标记，或用 Computer Use 检查游戏；不能以进程存活判定加载成功。 |
| JSON 失败 | 读取 `error/hint` 与 stderr；补齐缺少参数，不向 stdin 注入向导答案。 |

`--non-interactive` 不禁止游戏窗口，`run --no-gui` 只关闭辅助 GUI。
发布、卸载和实例删除分别使用其明确选项，非交互不等同于同意这些操作。

## 截图与键盘输入

使用 `game_window.py`，传入当前项目与会话，不能直接指定任意 PID。
焦点失败时激活游戏；遮挡或屏幕外错误时调整窗口。游戏启动加载期可能暂时没有窗口，等待后重试。
截图采用可见客户区捕获，不承诺后台、遮挡或独占全屏捕获。全黑时改用窗口化模式或 Computer Use。
脚本只负责发送按键；游戏不响应时先查看最新截图，不要直接追加重复按键。

键名未覆盖时可用 VK/SC/E0 代码。Fn 等硬件层按键、Windows 安全组合键不能保证软件模拟；系统快捷键和媒体键可能由系统处理而非游戏。
长按或组合移动时若游戏失去焦点，脚本会停止等待并释放本次按键。释放失败必须先检查键盘状态，不能直接重复动作。

## 网络与登录组件

- `connect --help` 没有 `--detach`：旧 CLI 只有前台网络连接，不能用于会话窗口脚本。显式选择具备网络会话的版本／源码后升级；不改脚本接受任意 PID。
- 临时连接的 `--project` 仅决定会话保存位置。后续 status/logs/stop 和窗口脚本都用启动返回的 `project`，不依赖当前目录；不要提前删除此目录。
- 网络 `--json` 必须配合 `--detach`。前台网络 Ctrl+C 停止本次游戏；后台通过 `stop --session` 停止。
- `doctor --mcs-auth --json` 的组件结果与游戏资源诊断分别报告。`component_available` 只表示文件具备；`trust_verified/login_verified` 为 false，不能推断证书可信或账号已登录。
- `component_unavailable`：优先使用正式发布包。仓库不保存编译后的桥接组件，Git／可编辑安装可能缺失；只有源码开发任务才参考仓库的 `docs/mcs-auth.md` 构建，并设置 `MCPY_MCS_BRIDGE_DIR`。单独复制的 Skill 无需附带仓库文档。
- `studio_unavailable`：由用户打开并登录 MC Studio；多个实例时明确目标。`component_blocked`：报告策略阻止，不自动安装证书或关闭保护。身份过期需重新登录并重启测试，当前不自动刷新。
- `identity_provided=true` 表示已提供 MCS 身份，`authenticated=false`、`connection_verified=false` 表示工具尚未证明服务端认证／进服。按日志或界面验证，不把这些字段简单视为成功或失败。

键盘使用 `+` 或空格表示同时按住，例如 `key W A --hold-ms 1000` 斜向移动，`key CTRL+W SPACE --hold-ms 500` 同时冲刺跳跃，实际效果依游戏设置。
默认按住 80 ms；命名修饰键先按下，逆序释放，期间持续检查焦点。不提供跨调用持续 key-down。
`VK:0xNN` 为 Windows 虚拟键，`SC:0xNN` 为物理扫描码，`E0:0xNN` 为扩展扫描码；OEM 键含义依键盘布局，`NUMPAD_ENTER` 与 `ENTER` 分开。

## Windows 编码

Skill 的 Python 脚本和 CLI 的 JSON 使用 ASCII 转义，`json.loads`／`ConvertFrom-Json` 会还原中文及特殊字符；不要对原始 JSON 文本查找中文日志标记。
bootstrap 保留 UTF-8 BOM，以便 Windows PowerShell 5.1 正确读取源码，并显式使用 UTF-8 子进程管道；不要另存为 ANSI 或移除 BOM。
脚本调用 Python CLI 时指定 UTF-8，接受可选 BOM。会话中的 SDK／引擎日志兼容 UTF-8、GBK/GB18030 输入，统一写成 UTF-8；按完整行解码后脱敏。
PowerShell 5.1 的 `>`／`Out-File` 默认可能生成 UTF-16 文件，需另存 JSON 时显式用 `Out-File -Encoding utf8`，读取使用 UTF-8（允许 BOM），不要依赖系统默认编码。
