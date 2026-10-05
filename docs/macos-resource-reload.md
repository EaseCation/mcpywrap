# macOS 资源热更验收

2026-10-05，Apple Silicon、ANGLE Metal、开发者 APK 3.9.100.297020。使用独立 ResourceReloadProbe Addon/世界和原生运行包 macos-arm64-0.1.0-preview.local5（旧入口）及 local6（原生 JSON UI 入口）；未修改真实项目或联网登录。

| 类型 | 当前支持情况 | 实测依据 |
|---|---|---|
| Python | 支持客户端/服务端模块热更 | 前轮手动及自动监控均读取到新值；不自动重建既有对象或事件订阅 |
| JSON UI | local6 起支持定义重载，需重建自定义界面 | 同一进程/世界调用原生 reload，重新注册创建 UI 后读取到新文字、颜色，并验证按钮回调；旧 Ctrl+R 路径仍无效 |
| 微软粒子 | 已有文件可热更 | 已知粒子 JSON 加入 creation_expression 后，同一进程新建发射器的 GetVariable 读到 42；再次改为新标识和数值后读到 84 |
| 材质 | 当前 mcpy 入口不支持，底层仍待适配 | clientlevel 包装层没有 reload_one_material_file；_clientlevel 原生层虽有导出，但返回 True 未证明示例材质刷新，不能据此宣称可用 |
| Shader | Metal 路径尚未验证，暂不开放该版本入口 | 函数存在，但没有安全、有效的动态重编译验收；此前 Windows 引擎已出现过 Shader 调用阻塞，本轮没有对 Mac 发起 Shader 重编译 |
| 纹理、模型、方块/物品等其他 JSON | 没有专用热更入口 | 使用重新部署并重载世界；不能从 reload 命令存在推断支持所有资源 |

## JSON UI 原生入口（已实现）

`runtime reload ui --session <sid> --json` 与 Qt 共用同一后端。安装声明 json_ui_reload_protocol=1 的运行包后，需要启动新实例，旧世界实例不会自动换包。后台部署后，客户端调用 `_mcpy_launcher.reload_ui()`；不存在该模块/方法时返回 unsupported，引擎拒绝返回 failed。新能力仅用于开发调试，不可作为 Mod 业务依赖。

适配器复用 C++ MinecraftGame::handleReloadUIDefinitions，仅支持已验证 ELF SHA-256；没有修改游戏机器码，版本相关 ABI 集中在启动器单独文件。后续 APK 需重新确认，不能认为所有 Android 包通用。

定义加载是异步的，已有 UI 控件和句柄可能失效。此包实测不触发 UiInitFinished，需要按 Mod 逻辑重新 RegisterUI/CreateUI 并绑定回调；不自动保留界面状态、不模拟初始化事件。测试已证明现有 JSON 的文字/颜色/新增按钮生效，重新绑定的按钮在两轮点击中计数 1→2。错误 JSON 请求也可能返回 True；修正文件并重载后恢复，但没有自动回滚保证。新增文件和复杂继承尚未验收。

产品验收 PID 51903、世界 83396a80237a4efdb4afd3d0b0345cae，公开命令之后从 AFTER C 读取到 PRODUCT OK；同一世界和进程未重启。原生实验另用截图核对绿色 AFTER A、蓝色 AFTER B。证据为 launcher 的 stability/ui-product-*.json 和 ui-button-click-two.json。测试结束已保存关闭游戏和 worker。

## JSON UI 旧入口对照

通过正式 RegisterUI/CreateUI 创建临时标签，使用 Label.GetText 检查定义值。源码更新后，实例 assembled 中的 JSON 确实包含新值，故失败并非软链接或部署遗漏。Ctrl+R 的脚本接口接受了四个按键事件，但不刷新 UI 定义；真实窗口 Ctrl+R 也没有刷新。Android 包没有 _ui_editor，不能沿用其 reload_ui_file。

额外试过 ForceReloadResourcePack 和 reload_user_pack：前者返回 True、后者无返回值，均未使测试 UI 定义更新。某组全资源/底层材质刷新试验之后观察到渲染异常，尚未归因到单个调用；这些宽泛接口没有作为替代方案接入产品。测试进程已正常保存关闭。

## 粒子边界与回执

_particle_system.load 连不存在的路径都返回 True，因此它只是加载请求的回执。新文件在本次运行中没有被识别（Create 返回 0、get_emitter_exist=False），重开世界后有效。已有文件热更后的新发射器则存在，并读到修改后的 Molang 值。当前验证不包括已运行发射器的自动更新。

资源请求现统一报告 triggered、effect_verified=false，不能把脚本返回 completed 等同于效果已生效。Python 仍报告 completed，按原规则检查返回值。新增资源未被识别时提示重载世界。

## 产品处理

平台差异留在后端的 reload_restriction；CLI、主界面和小窗共用 reload_session。对于当前 macOS 开发包，材质和 Shader 在部署/调用之前返回 unsupported；JSON UI 根据实例固定运行包的 json_ui_reload_protocol 检查能力，旧包仍返回 unsupported，新包通过客户端 _mcpy_launcher.reload_ui 调用引擎定义重载。已有粒子文件的热更入口保留。限制按已验收的 APK 版本定位，不声称其他版本也已验证。

资源热更仍为手动操作；runtime watch 默认仅自动热更 Python。资源变化会提示手动检查或重载世界。

证据保留在 launcher 的 build-macos-arm64/stability/resource-*.json。关键对照为 resource-reload-ui-after.json、resource-ui-recreate-after-force.json、resource-baseline2.json、resource-particle-modified-marker.json、resource-particle-second-marker.json、resource-public-check.json。
