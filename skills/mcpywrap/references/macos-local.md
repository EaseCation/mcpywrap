# Apple Silicon macOS：资源与平台差异

仅在安装/升级资源、解释平台能力或引擎限制时读本页。普通启动、世界保留和部署规则见[本地生命周期](local-development.md)，不用为 macOS 编写另一套日常操作流程。

## 安装与检查

```text
mcpy --local doctor --capabilities --json
mcpy --local engine doctor --json
mcpy --local --non-interactive engine install --json
```

需要 macos-local-worlds 能力；Intel Mac 不支持原生本地后端，Apple Silicon 上的 Rosetta Python 可启动 arm64 游戏。engine install 是可选的提前准备；首次 run 资源缺失时会自动安装，不要求用户提供 catalog 或 APK。

默认通过固定 HTTPS 启动器发行源及网易 pe 动态发现开发者 APK。显式 --catalog、MCPY_RUNTIME_CATALOG 或已保存来源优先；--apk 仅用于已有匹配 APK 的离线导入。下载/提取进度写 stderr，stdout JSON 保持独立。

资源默认位于 `~/Library/Application Support/mcpy`，MCPY_ENGINE_HOME 可隔离测试。无需 Wine、Homebrew 游戏环境、MPay 账号或安装另一套 Launcher。网络、校验、空间或结构检查失败按原错误处理，不猜 CDN 版本路径，不关闭系统保护。

官方动态 APK 初次下载没有预发布可信摘要；工具在来源、下载一致性、归档和结构检查后记录实际摘要。不能把缓存校验误说成官方签名身份背书。最低声明 macOS 13.0；已记录游戏实测为 26.6.2，运行包 ad-hoc 签名未公证，不能据此保证最低系统/Gatekeeper 全部通过。

## 实例固定版本与升级

每个世界实例固定运行包与 APK；engine install 不迁移既有世界。旧实例继续使用旧资源，新能力通常需要升级后 run --new。若用户要保留世界，先说明绑定与能力限制，不擅自删除重建或直接改旧实例的版本号。

```text
mcpy --local engine check-updates --json
```

此命令只发现网易 pe/pe_old 的真实版本和 URL，不下载；compatibility=not_checked 不能当作可运行。首次安装已会查询 pe，无需为了普通启动先检查更新。

CLI 0.6.1 默认使用运行包 0.4.6，包含原生游戏截图和后台窗口协议。全新安装直接 run 即可自动准备；已有安装保留所选来源，升级资源时明确指定：

```text
mcpy --local --non-interactive engine install --catalog https://github.com/EaseCation/mcpelauncher-manifest/releases/download/mcpy-runtime-v0.4.6/catalog.json --json
```

此 catalog 仍按其来源规则发现 APK，不等于固定旧 APK。旧版本若不在官方频道无法下载时，报告缺失，不猜 URL。更新 CLI/Skill 或重新 runtime install 都不能替换原生包。

## 平台能力边界

| 能力 | 当前边界 |
|---|---|
| 本地世界 | Addon；Map 尚未接入。Map 需 Windows 本地运行，远程服务不提供世界实例 |
| 世界参数 | 运行包 cppconfig_protocol=1；选项见[世界设置](instance-world-settings.md) |
| 游戏 Python | 本地 client/server；客户端队列需 python.client_queue，使用见[运行时调试](runtime-debug.md) |
| 无认证网络 | 运行包 0.4.3+ 且 network_connect_protocol=1；服务器须允许开发客户端 |
| 本地主客机 | 尚不支持；缺 local-dual-client-manual 时启动前拒绝 |
| 双外服客户端 | 需要独立开发身份协议的原生包；已做候选实验不代表公开 0.4.5 已具备，按实际能力拒绝或使用已明确选择的构建 |
| MCS 身份 / MCEditor | macOS 不支持；MCS 网络身份可由 Windows 服务提供，编辑器必须 Windows 本机 |
| 游戏截图 | 需要实例运行包 screenshot_protocol=1；按需获取游戏帧，见[画面采集](capture.md#截图) |
| 后台窗口 | 需要 background_window_protocol=1；旧包明确拒绝，允许聚焦时显式 --foreground；运行包构建补丁见仓库 native/background_window |
| 录屏/视频提帧/原始设备输入 | macOS 本地不支持；远程可针对 Windows 会话使用 |

网络使用与结果判断见[网络会话](network-sessions.md)。3.10.100.299889 曾在本机允许无认证的 Nemisys/SynapseAPI/Nukkit 测试栈验证进服，不能推及公开服务器。当前网络运行包对外 HTTP 资源包下载未完成验收；需要这类分发时不能宣称完整支持。

## 游戏输入与资源重载

- 运行包 0.4.4 提供单调时钟，目标会话应报告 clock_source=launcher.steady_clock。旧包 missing_monotonic_clock 需明确升级并新建实例，不替换为 CPU/墙钟或旧输入协议。统一输入步骤见[输入页](runtime-input.md)。
- 输入计时、移动跳跃、取消释放、攻击、聊天和 UI 点击已在 26.6.2 / 开发包 3.9.100.297020 验证；3.10.100.299889 的时钟适配记录为结构检查，不能说成同等游戏输入实测。
- JSON UI 需要 json_ui_reload_protocol=1；旧包 Ctrl+R 无效。重载后须重新创建业务界面和回调，不依赖 UiInitFinished 自动重建。3.9.100.297020 与 3.10.100.299889 已有定义重载验证，新文件/复杂继承仍需单独确认。
- 已有微软粒子文件更新后检查新建发射器；新增粒子可能需要重开世界。Material/Metal Shader 当前返回 unsupported，不通过宽泛资源刷新接口绕过。
- 原生结构预检失败返回 unsupported_engine_structure；JSON UI 的局部定位失败可只关闭该能力。发现新 APK 不自动启用未验证的资源接口。

重载语义、端侧和实际效果验收统一见运行时调试页，不把 triggered 当作画面成功。

## 用户偏好与运行文件

画面、音量、GUI 缩放和输入偏好由 worker 按用户保存到资源根 `preferences/macos`，新会话导入；它们不是 cppconfig 世界设置，运行中的其他实例不即时跟随。正常退出以便原生配置写回。

addon_link_protocol=1 的运行包读取实例 assembled 目录；旧包有复制兼容流程。不要修改内部链接、直接写 assembled 或开启额外监听器。Qt 与 CLI 共用会话服务，窗口关闭与停止游戏的规则见本地生命周期页。
