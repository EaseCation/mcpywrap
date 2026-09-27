# 遇到问题时再读

| 现象 | 下一步 |
|---|---|
| 没有 `--project` 或 `status` | 当前 CLI 版本缺少能力；选择支持此 Skill 的版本或源码提交重新安装，不猜测参数。 |
| uv 报 Python 版本链接失效 | Python bootstrap 用 `--python <本机解释器路径>`，PowerShell 用 `-Python <路径>`，避免依赖失效的次版本链接。 |
| `init` 拒绝已有配置 | 直接使用现有项目，必要时执行 `sync`；不要删除配置来绕过保护。 |
| 本地依赖结构无效 | 检查引用是否为 Addon 根目录，是否包含有 manifest 的行为包或资源包。 |
| Python 依赖未安装 | 按错误提示执行明确的 `add "requirement"`。本地目录引用不会自动安装其包依赖。 |
| 仅开发环境／游戏中 import 失败 | 包安装于工具环境，不会自动进入游戏；检查实际 Addon 内容、游戏解释器兼容性与加载日志。 |
| 游戏包包含原生二进制 | 将开发依赖移出游戏包，或使用适配游戏的纯 Python 实现；不要删除校验或反复安装来绕过。 |
| 游戏或皮肤未找到 | 先确认执行位置。远程任务在 Windows 上补齐资源／修改 serve 参数，不在 macOS 安装游戏或指定 Windows 路径。 |
| 指定版本不存在 | 从 doctor 的候选中选择用户认可的完整版本，不静默升级。 |
| 游戏启动失败或超时 | 查看会话状态、`worker.log`、SDK 的 `game.log` 和引擎的 `engine.log`；避免无依据重复启动。 |
| PID 身份不匹配 | 不终止该进程；会话可能过期，重新确认目标。 |
| 运行正常但没有加载证据 | 查找日志标记或查看会话截图；本机可使用 Computer Use，远程用下载的图片；不能以进程存活判定加载成功。 |
| unauthorized | 检查两端 MCPY_REMOTE_TOKEN；它和 MCS 登录无关。 |
| remote_unavailable / protocol_mismatch / capability_missing | 检查 Windows 服务地址与相应端版本；不回退本机或反复升级到同一旧版本。 |
| JSON 失败 | 读取 `error/hint` 与 stderr；补齐缺少参数，不向 stdin 注入向导答案。 |

`--non-interactive` 不禁止游戏窗口，`run --no-gui` 只关闭辅助 GUI。
发布、卸载和实例删除分别使用其明确选项，非交互不等同于同意这些操作。

## 截图与键盘输入

优先用 screenshot/key/mouse CLI；兼容脚本传入本机 project、同一远端 endpoint 和 session，不能直接指定任意 PID。
焦点失败时激活游戏；遮挡或屏幕外错误时调整窗口。游戏启动加载期可能暂时没有窗口，等待后重试。
截图采用可见客户区捕获，不承诺后台、遮挡或独占全屏捕获。全黑时在 Windows 改用窗口化模式；本机可按环境能力使用 Computer Use，不能让 macOS 工具操作不可见的远端桌面。
窗口命令只负责发送输入；游戏不响应时先查看最新截图，不要直接追加重复按键。

键名未覆盖时可用 VK/SC/E0 代码。Fn 等硬件层按键、Windows 安全组合键不能保证软件模拟；系统快捷键和媒体键可能由系统处理而非游戏。
长按或组合移动时若游戏失去焦点，脚本会停止等待并释放本次按键。释放失败必须先检查键盘状态，不能直接重复动作。

## 网络与登录组件

- `connect --help` 没有 `--detach`：旧 CLI 只有前台网络连接，不能用于会话窗口脚本。显式选择具备网络会话的版本／源码后升级；不改脚本接受任意 PID。
- 本机 connect 的 project 决定本机会话位置；远程 connect 的会话在 Windows serve data-dir。后续用返回的 endpoint/session/project，不把 remote_project 当成本机目录。
- 远程启动必须 --detach，之后通过 stop 停止；只有本机网络支持前台 Ctrl+C 停游戏。
- `doctor --mcs-auth --json` 的组件结果与游戏资源诊断分别报告。`component_available` 只表示文件具备；`trust_verified/login_verified` 为 false，不能推断证书可信或账号已登录。
- `component_unavailable`：优先使用正式发布包。仓库不保存编译后的桥接组件，Git／可编辑安装可能缺失；只有源码开发任务才参考仓库的 `docs/mcs-auth.md` 构建，并设置 `MCPY_MCS_BRIDGE_DIR`。单独复制的 Skill 无需附带仓库文档。
- `studio_unavailable`：由用户打开并登录 MC Studio；多个实例时明确目标。`component_blocked`：报告策略阻止，不自动安装证书或关闭保护。身份过期需重新登录并重启测试，当前不自动刷新。
- `identity_provided=true` 表示已提供 MCS 身份，`authenticated=false`、`connection_verified=false` 表示工具尚未证明服务端认证／进服。按日志或界面验证，不把这些字段简单视为成功或失败。

键盘使用 `+` 或空格表示同时按住，例如 `key W A --hold-ms 1000` 斜向移动，`key CTRL+W SPACE --hold-ms 500` 同时冲刺跳跃，实际效果依游戏设置。
默认按住 80 ms；命名修饰键先按下，逆序释放，期间持续检查焦点。不提供跨调用持续 key-down。
`VK:0xNN` 为 Windows 虚拟键，`SC:0xNN` 为物理扫描码，`E0:0xNN` 为扩展扫描码；OEM 键含义依键盘布局，`NUMPAD_ENTER` 与 `ENTER` 分开。

## Windows 编码

Skill 的 Python 脚本和 CLI 的 JSON 使用 ASCII 转义，`json.loads`／`ConvertFrom-Json` 会还原中文及特殊字符；不要对原始 JSON 文本查找中文日志标记。
bootstrap.ps1 保留 UTF-8 BOM，以便 Windows PowerShell 5.1 正确读取源码，并显式使用 UTF-8 子进程管道；不要另存为 ANSI 或移除 BOM。
脚本调用 Python CLI 时指定 UTF-8，接受可选 BOM。会话中的 SDK／引擎日志兼容 UTF-8、GBK/GB18030 输入，统一写成 UTF-8；按完整行解码后脱敏。
PowerShell 5.1 的 `>`／`Out-File` 默认可能生成 UTF-16 文件，需另存 JSON 时显式用 `Out-File -Encoding utf8`，读取使用 UTF-8（允许 BOM），不要依赖系统默认编码。

远程连接与鼠标操作的问题见[远程测试](remote-testing.md)。远端不可用不会切换为本机运行；macOS 上仅安装 CLI 客户端不需要 Qt 或 Windows 游戏。
