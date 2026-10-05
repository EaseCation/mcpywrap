# macOS 资源热更参考

资源能力取决于实例固定的原生运行包和匹配 APK。以下边界适用于开发者 APK 3.9.100.297020 / ANGLE Metal；其他资源包版本应重新检查能力与效果。

| 类型 | 支持与限制 |
|---|---|
| Python | 客户端/服务端已加载模块可更新命名空间；不会自动重建对象和事件订阅 |
| JSON UI | 运行包声明 json_ui_reload_protocol=1 才支持原生定义重载；需重新创建业务界面和回调 |
| 微软粒子 | 已有文件更新后新建发射器；新增文件或既有发射器变化需单独检查，必要时重载世界 |
| 材质、Shader | 当前 macOS 入口返回 unsupported，不通过宽泛资源刷新函数代替 |
| 纹理、模型、方块/物品等其他 JSON | 没有专用热更入口，重新部署并重载世界 |

`runtime reload ui --session <sid> --json` 与 Qt 共用后端。安装新运行包后须新建实例，旧实例不会自动换包。客户端调用 `_mcpy_launcher.reload_ui()`，模块/方法不存在时返回 unsupported，引擎拒绝返回 failed。该接口只供开发调试，不能成为 Mod 业务依赖。

适配器复用 MinecraftGame::handleReloadUIDefinitions，ABI 与受支持 ELF 摘要由原生启动器维护；不能认为任意 Android APK 通用。Windows 的 Ctrl+R 路径不适用于此后端，不能因按键投递成功便宣称 UI 定义已刷新。

定义加载异步执行，现有控件和句柄可能失效；须按 Mod 原有逻辑重新 RegisterUI/CreateUI 和绑定回调，不自动保留界面状态或模拟初始化事件。错误 JSON 的接受回执不保证加载成功，也不提供自动回滚。

粒子加载接口的 True 仅为请求回执，应检查新发射器是否存在并读回 Molang/业务值。新增资源未识别时应重载世界。

资源热更统一返回 triggered、effect_verified=false；Python 脚本仍返回 completed。平台限制在部署/调用前检查，Qt 与 CLI 共用规则。runtime watch 自动热更 Python，资源变化提示手动检查或重载世界。

通用游戏内 UI/玩家能力可通过 [可选手动测试](../tests/manual/runtime_controls/README.md) 检查；资源热更另需对应 Mod 的效果验证，不能用按钮或脚本回执代替。
