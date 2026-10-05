# Windows / macOS 共用的 Qt6 开发界面

安装 mcpywrap 时，Windows 和 macOS 都使用 PySide6-Essentials（Qt6），仅使用 QtCore、QtGui、QtWidgets，无需 PyQt 或 PySide6-Addons。命令行仍延迟导入 Qt，AI 和脚本继续使用 `--non-interactive --no-gui --detach --json`。

```sh
mcpy --local --project /path/to/addon ui
# 人工终端 run 默认打开同一个界面并启动实例
mcpy --local --project /path/to/addon run
# 终端模式
mcpy --local --project /path/to/addon run --no-gui
```

首次 macOS 使用“运行环境”安装资源（同 CLI 的 catalog/APK 安装服务）；默认无公开发行源，需要发行方的 catalog。测试用本地资源已放在独立目录，可这样打开已有测试项目：

```sh
MCPY_ENGINE_HOME=/Users/fangyizhou/Documents/coding/mcpelauncher-manifest/build-macos-arm64/product-engine-home \
  mcpy --local --project /Users/fangyizhou/Documents/coding/mcpelauncher-manifest/build-macos-arm64/product-smoke-project ui
```

界面复用原有项目/依赖布局，支持本地、包、Git 依赖与框架快捷添加，Mod 模板、实例创建/选择/删除、运行环境安装、保存退出和重新部署重载世界。macOS 明确显示并禁用“MCEditor（不支持）”；Windows 继续使用其 MC Studio Editor。

## 公共实现与平台边界

GameInstanceManager 不检查操作系统，也不直接构造 cppconfig 或启动原生游戏；项目页和折叠小窗共用 SessionController，再通过 GameBackend 和现有会话服务调度。WindowsBackend 继续使用 MC Studio 发现和原有启动配置，MacOSBackend 使用 APK 及原生启动器。两者共用 sessions、FileLogServer、RuntimeControlServer、ProjectWatcher 和 SessionWatcher。

Debug 日志页与自动弹出的折叠小窗共用一次读取、同一缓存和 LogView；恢复原有染色、搜索及前后跳转，支持来源和协议详情切换。关闭小窗只隐藏视图。结构与生命周期见 [共用日志界面](shared-log-ui.md)。Python 控制台显式选择 client/server；macOS 客户端走 JNI 通道，服务端仍使用原有 Safaia。

只自动关闭本窗口启动的会话；复用的既有会话不会因关闭管理页而被停止。关闭拥有游戏的管理器时确认保存退出，后台线程完成后才销毁窗口；操作中不会销毁正在运行的 QThread。

## 热更与软链接

```sh
mcpy --local --project /path/to/addon runtime reload python --session <id> --file /path/to/module.py --side client --json
mcpy --local --project /path/to/addon runtime watch --session <id> --side server
```

GUI 和 CLI 共用 SessionWatcher：成功组装后防抖，向指定端侧发送最新源码。默认 client，server 用于服务端模块，both 仅适合可以安全重复执行的公共模块。未加载模块会明确跳过。停止监控不关闭游戏。

Python 模块热更更新模块命名空间；不会自动重建已有对象、替换已注册的回调或撤销之前的副作用。修改事件注册、类结构、新增入口、删除模块或不支持动态加载的资源时，使用“重新部署并重载世界”。该按钮保存退出、重新组装、重开同一世界，不新建或丢弃存档。

资源热更按实际后端能力处理：当前 macOS 开发包支持已知粒子文件更新；local6 起的运行包通过原生入口重载 JSON UI 定义，须重新注册/创建界面及绑定回调，Qt 与 CLI 共用结果和提示。旧运行包的 JSON UI、当前材质和 Shader 返回 unsupported。资源回执为 triggered，仍须检查实际效果。详见 [macOS 资源热更验收](macos-resource-reload.md)。

新原生运行包声明 addon_link_protocol=1，使用 `--link-source-addons`：游戏行为包/资源包目录软链接到实例 assembled 目录，packs 中的标准名称也只是链接。主项目和依赖继续由同一组装器合并，监控直接更新组装目录，无需再复制运行副本。原始项目和依赖不移动、不删除。旧实例仍固定旧运行包，保留复制兼容路径；升级运行包后新建实例才启用新协议。

## 验证与范围

在 Apple M1 Max / macOS 26.6.2 实际打开 Qt6 Cocoa 窗口，验证原生 Metal 游戏启动、两包软链接、普通 Mod 调试日志持续显示、Python 控制台、客户端/服务端源码值变化、自动监控、重开原世界和关闭窗口保存退出。最小探针、OreDetector、Ration 使用现有项目构建流程。证据在 launcher 的 build-macos-arm64/stability/pyside6-gui-smoke.json、qt6-hot-reload-result.json 和界面截图。

本机安装 PySide6-Essentials 6.11.2 / Qt 6.11.2，QtCore Mach-O 的最低系统标记为 macOS 13.0；原生游戏组件的构建目标仍为 11.0，两者不能混为一个已验证下限。当前 Windows 侧由共用接口和 Qt 测试回归，尚未进行新的 Windows 实机验收。MCEditor、MCS 身份、Windows 桌面输入/录制不因此变成 macOS 功能。


## Qt 绑定的发行许可

mcpy 自身继续使用 MIT；GUI 改为 PySide6-Essentials 和 Shiboken6，选择其 LGPLv3 许可路线。当前 wheel 元数据声明 LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。Qt/PySide 作为用户 Python 环境中的独立动态依赖安装，mcpy wheel 不内嵌这些库，也不限制用户替换兼容版本。原生 launcher 仍按其自身 GPL 许可提供对应源码。

发行时保留 Qt/PySide 的版权、许可及第三方声明，并提供适用 LGPL 组件的对应源码获取方式。若以后改为冻结桌面应用、直接捆绑 Qt 或使用其他 Qt 模块，需要重新核对实际模块及重新链接/替换要求。切换 PySide6 消除的是 PyQt GPL 绑定依赖，不是免除所有第三方许可义务。上游许可信息见 https://doc.qt.io/qtforpython-6/licenses.html 。

PySide6 迁移验证：443 项回归运行成功（419 通过，24 平台相关跳过）；本机 GUI 完成日志、Python 控制台、双端热更、原世界重载和保存关闭。迁移时已从 mcpy 专用环境移除 PyQt6，未提供双绑定回退。后台结果通过显式 Slot 更新主线程界面，线程归属测试通过。发行声明随 wheel 携带于 THIRD_PARTY_NOTICES.md。
