# macOS 统一输入时钟适配

正式发行对应 CLI 0.4.6 / macOS 原生运行包 0.4.4。安装与旧实例升级步骤见
[macOS 本地测试](../../skills/mcpywrap/references/macos-local.md#统一输入时钟修复cli-046--运行包-044)。

`steady_clock.h` 提供平台原生单调秒值，供游戏内 Python 2 的 `_mcpy_launcher.monotonic()` 使用。mcpywrap 在能力查询时检测此方法；缺失时返回 `missing_monotonic_clock`，不退回 CPU 时间、墙上时间或脚本回调计数。

`launcher-monotonic.patch` 面向 EaseCation/mcpelauncher-client 的 netease-macos-arm64 分支，为现有临时模块增加单调时钟。必须先由运行包的经过验证的二进制结构分析提供 `ui.floatFromDouble`（真实 CPython `PyFloat_FromDouble`）绑定；补丁只在该绑定存在时注册方法，不猜地址或复用其他 ABI。

`manifest-monotonic.patch` 配套应用到 EaseCation/mcpelauncher-manifest，补齐此前缺失的构造函数结构规则、识别器、运行包能力标记和拒绝错误绑定的测试。识别器从游戏 CPython 的 `math.fabs` 和 `math.ceil` 注册表出发，验证二者汇合到同一个已审计的数学包装函数，再验证其 `PyFloat_FromDouble` 返回路径及完整构造函数。发布规则只保留规范化指令摘要，不包含按版本猜测的地址表。时钟规则失败时保留原有 UI 重载能力，不注册时钟。

两份补丁必须同时编译进新运行包；只更新 CLI、重新 `runtime install` 或只应用启动器补丁，均不能修复旧包的 `missing_monotonic_clock`。本仓库不包含启动器完整编译依赖或游戏 ELF。

在启动器 manifest 仓库应用配套补丁、在其 `mcpelauncher-client` 子模块应用 launcher 补丁后，使用 `tools/build_macos_runtime.py` 和 `tools/package_macos_release.py` 构建不可变的新运行包。通过公开 `mcpy --local engine install --catalog <新目录/catalog.json> --apk <已校验开发者APK>` 安装，再用 `run --new --no-gui --detach` 创建测试实例。已有世界固定旧运行包，不直接改写签名应用或实例绑定。

原生运行包交付前必须在实际 Apple Silicon Mac 上：验证结构绑定、编译启动器、核对空闲/暂停前后时钟递增且不受系统时间调整影响、检查新统一 key/玩家/UI 输入与取消释放。运行包随实例固定，不自动替换已有实例；无需也不得安装业务 Mod 来提供调试时钟。

纯时钟 smoke 可以在有 C++11 编译器的宿主执行，验证 primitive 本身；这不能替代 Mac 的 Python ABI 或游戏实机验收。

`tests/manual_runtime_input_unified.py` 为可选实机验收：macOS 通过公共客户端 Python 检查 HUD 就绪，验证空闲/暂停计时、临时 Python 墙钟变化独立性、三次重叠移动跳跃、持键取消释放、移动中攻击、菜单按键和 UI 点击。测试只修改显式指定的专用世界，结果及原始操作保存在 `--output` 目录；不会调整操作系统时间。

## 2026-10-17 本地验收

Apple Silicon / macOS 26.6.2 / 开发包 3.9.100.297020，已构建并通过公开安装入口安装
`macos-arm64-0.4.5-input-clock.1`。当前会话实际报告 `clock_source=launcher.steady_clock`。
8 项实机用例全部通过：空闲/暂停计时、三次移动跳跃叠加、SHIFT+W 取消释放、移动中攻击、
T/ESC 聊天开关、CTRL+UI 点击设置。三次跳跃高度均约 1.252 格，SPACE 释放后 W 继续移动
4.95–5.60 格；攻击由服务端确认生命值 100 → 95，并核对伤害来源。测试会话已保存退出。

CLI 输入/UI 回归 116 项、验收脚本/技能契约 8 项、原生结构规则 8 项及 CTest 3 项通过。
3.10.100.299889 也通过了时钟绑定结构检查，本次完整游戏操作验收只针对 3.9。
本地报告位于 `test/macos-input-clock/final-acceptance/report.json`（含完整命令和观测），
精简结果为同目录 `summary.json`。这是本地修复包；更新 CLI 不会把新时钟带入已固定旧包的实例。
