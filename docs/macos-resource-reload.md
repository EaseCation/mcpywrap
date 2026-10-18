# macOS 资源热更参考

本页保留原生适配机制与验证记录。用户操作统一见 Skill 的 [运行时调试](../skills/mcpywrap/references/runtime-debug.md) 与 [macOS 平台边界](../skills/mcpywrap/references/macos-local.md)，不要从底层接口名称推断可直接用于业务代码。

适配器复用 MinecraftGame::handleReloadUIDefinitions，ABI 与受支持 ELF 摘要由原生启动器维护；不能认为任意 Android APK 通用。Windows 的 Ctrl+R 路径不适用于此后端，不能因按键投递成功便宣称 UI 定义已刷新。

定义加载异步执行，现有控件和句柄可能失效；须按 Mod 原有逻辑重新 RegisterUI/CreateUI 和绑定回调，不自动保留界面状态或模拟初始化事件。错误 JSON 的接受回执不保证加载成功，也不提供自动回滚。

粒子加载接口的 True 仅为请求回执，应检查新发射器是否存在并读回 Molang/业务值。新增资源未识别时应重载世界。

资源热更统一返回 triggered、effect_verified=false；Python 脚本仍返回 completed。平台限制在部署/调用前检查，Qt 与 CLI 共用规则。runtime watch 自动热更 Python，资源变化提示手动检查或重载世界。

通用游戏内 UI/玩家能力可通过 [可选手动测试](../tests/manual/runtime_controls/README.md) 检查；资源热更另需对应 Mod 的效果验证，不能用按钮或脚本回执代替。

3.10.100.299889 也已验证定义重载；新运行包按 ELF 结构识别接口，同一运行包可服务多个 APK 版本，仍需重新注册/创建界面；材质包装接口缺失，Metal Shader 尚未验证，两个入口继续返回 unsupported。切换 APK 版本后需新建实例，不能直接改动旧实例的引擎版本号。

结构规则运行包在安装与启动前执行预检，核心结构无法确认时返回 `unsupported_engine_structure` 和诊断路径，不改变已选版本。JSON UI 定位失败单独返回 unsupported，不影响离线世界启动。新 APK 的版本号不会自动启用尚未验证的 Material/Metal Shader 热更。启动器来源由发行 catalog 管理，默认 APK 来源按网易 pe 发现；结构兼容不等于任意新 APK 的全部能力已获实机验证。
