# Windows / macOS 共用的 Qt6 开发界面

安装 mcpywrap 时，Windows 和 macOS 都使用 PySide6-Essentials（Qt6），仅使用 QtCore、QtGui、QtWidgets，无需 PyQt 或 PySide6-Addons。命令行仍延迟导入 Qt，AI 和脚本继续使用 `--non-interactive --no-gui --detach --json`。

```sh
mcpy --local --project /path/to/addon ui
# run 在终端准备资源，游戏启动后只打开紧凑调试小窗
mcpy --local --project /path/to/addon run
# AI 或纯终端操作
mcpy --local --project /path/to/addon --non-interactive run --no-gui --detach --json
```

mcpy ui 内首次启动会自动准备 macOS 资源并显示进度，完成后继续启动。高级来源和本地 APK 导入默认折叠；与 CLI 复用同一个安装服务。

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

资源热更按实际后端能力处理：当前 macOS 开发包支持已知粒子文件更新；支持原生 JSON UI 重载协议的运行包可重载定义，之后须重新注册/创建界面及绑定回调，Qt 与 CLI 共用结果和提示。缺少该协议的运行包、当前材质和 Shader 返回 unsupported。资源回执为 triggered，仍须检查实际效果。详见 [macOS 资源热更](macos-resource-reload.md)。

新原生运行包声明 addon_link_protocol=1，使用 `--link-source-addons`：游戏行为包/资源包目录软链接到实例 assembled 目录，packs 中的标准名称也只是链接。主项目和依赖继续由同一组装器合并，监控直接更新组装目录，无需再复制运行副本。原始项目和依赖不移动、不删除。旧实例仍固定旧运行包，保留复制兼容路径；升级运行包后新建实例才启用新协议。

## 平台范围

Qt 依赖随 mcpy 自动安装，由包管理器根据 Python/系统版本选择兼容 wheel，无需手工配置插件路径。使用系统原生样式和调色板；悬浮窗默认宽 320 逻辑像素，置顶为原生 QToolButton 图钉，保留选中反馈、主题色和无障碍名称。

Qt GUI 的最低系统要求以实际 wheel 为准，不能用原生游戏组件的编译目标推断 GUI 支持范围。MCEditor、MCS 身份、Windows 桌面输入/录制不属于 macOS 功能。游戏内 UI/玩家控制的可选手动检查见 [运行时手动测试](../tests/manual/runtime_controls/README.md)。

## Qt 绑定的发行许可

mcpy 自身继续使用 MIT；GUI 改为 PySide6-Essentials 和 Shiboken6，选择其 LGPLv3 许可路线。当前 wheel 元数据声明 LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only。Qt/PySide 作为用户 Python 环境中的独立动态依赖安装，mcpy wheel 不内嵌这些库，也不限制用户替换兼容版本。原生 launcher 仍按其自身 GPL 许可提供对应源码。

发行时保留 Qt/PySide 的版权、许可及第三方声明，并提供适用 LGPL 组件的对应源码获取方式。若以后改为冻结桌面应用、直接捆绑 Qt 或使用其他 Qt 模块，需要重新核对实际模块及重新链接/替换要求。切换 PySide6 消除的是 PyQt GPL 绑定依赖，不是免除所有第三方许可义务。上游许可信息见 https://doc.qt.io/qtforpython-6/licenses.html 。

后台结果通过显式 Slot 更新主线程界面，发行声明随 wheel 携带于 THIRD_PARTY_NOTICES.md。

交互式 run 的调试小窗复用 SessionController/SessionLogWindow，不启动第二套日志服务。置顶使用原生 QCheckBox，随系统主题显示；关闭小窗只隐藏视图，游戏退出后清理控制器和监控。Ctrl+C 与“保存退出”调用同一停止接口。

## 应用图标

GUI 入口共用 `ui.application.create_application`：Qt 应用名与菜单显示名为 mcpy，管理页、日志小窗、模板和登录提示使用同一图标。Qt 的应用级图标也交给 Cocoa 用于 Dock。直接运行 Python 时，LaunchServices 仍可能把进程名称缓存为 Python；设置 Qt 显示名不等同于已安装独立 mcpy.app。已打开的小窗需要重新启动后应用新图标。

图标源为 `core/mcpywrap_core/ui/assets/mcpy.icon`，是可由 Icon Composer 27 编辑的分层文档：深蓝背景、薄荷绿方块、白色命令提示符。背景满幅不透明，前景 SVG 未预裁切；命令提示符保留不透明，以确保小尺寸对比度。不把 Minecraft 游戏图标用作 mcpy 品牌图标。

图标遵循 Apple [App icons HIG](https://developer.apple.com/design/human-interface-guidelines/app-icons) 和 [Icon Composer 文档](https://developer.apple.com/documentation/xcode/creating-your-app-icon-using-icon-composer)：

- 1024×1024 画布、sRGB；圆角遮罩、高光、边缘反射和层间阴影由 Apple 渲染器生成，不自行用固定半径模拟系统连续圆角。
- 方块范围 x=248–776、y=224–816，主要内容距离未裁切画布边缘至少 208 px。此数值是本设计的留白选择，HIG 并未规定统一的 macOS 安全区百分比。
- 分层源背景不预留透明外框。导出给传统 Qt/ICNS 的静态图标时，参考 actool 的 macOS 兼容输出，在 1024 画布内将系统渲染图形放入 824×824 区域，四周留 100 px 透明区，防止 Dock 中图标显得过大。分层源与静态兼容文件的留白不能混用。
- 图标已用 Icon Composer 27 渲染，并通过 Xcode 27 actool 编译。保留 `.icon` 原始分层素材，PNG 和 ICNS 则用于当前 Qt 应用；静态资源不具备随光照变化的动态 Liquid Glass，也不会自动切换 dark/clear/tinted 外观。将来独立打包 mcpy.app 时可接入编译后的 Assets.car，不能仅给 PNG 加反光就宣称支持全部动态外观。

ICNS 提供 16、32、128、256、512 点的 1×/2× 图像。wheel 包含静态图标和可编辑分层源，运行时无需 Xcode；图标维护见 [贡献指南](../CONTRIBUTING.md#图标资源)。
