# macOS 统一输入时钟适配

`steady_clock.h` 提供平台原生单调秒值，供游戏内 Python 2 的 `_mcpy_launcher.monotonic()` 使用。mcpywrap 在能力查询时检测此方法；缺失时返回 `missing_monotonic_clock`，不退回 CPU 时间、墙上时间或脚本回调计数。

`launcher-monotonic.patch` 面向 EaseCation/mcpelauncher-client 的 netease-macos-arm64 分支，为现有临时模块增加单调时钟。必须先由运行包的经过验证的二进制结构分析提供 `ui.floatFromDouble`（真实 CPython `PyFloat_FromDouble`）绑定；补丁只在该绑定存在时注册方法，不猜地址或复用其他 ABI。

当前 mcpywrap 仓库不包含启动器的完整编译依赖、受审计 Android ELF 或新增 CPython 构造函数的结构规则。补丁和时钟 primitive 可以审查；缺少该规则的旧运行包继续明确不支持时间规划。不要仅根据补丁存在就标记 macOS 支持。

原生运行包交付前必须在实际 Apple Silicon Mac 上：验证结构绑定、编译启动器、核对空闲/暂停前后时钟递增且不受系统时间调整影响、检查新统一 key/玩家/UI 输入与取消释放。运行包随实例固定，不自动替换已有实例；无需也不得安装业务 Mod 来提供调试时钟。

纯时钟 smoke 可以在有 C++11 编译器的宿主执行，验证 primitive 本身；这不能替代 Mac 的 Python ABI 或游戏实机验收。
