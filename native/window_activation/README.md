# Windows 后台窗口保护

`SW_SHOWNOACTIVATE` 只约束启动显示，目标引擎仍会主动请求激活。本组件使用线程级 `WH_CBT` 钩子：拒绝 `HCBT_ACTIVATE` / `HCBT_SETFOCUS`，为新建顶层窗口添加 `WS_EX_NOACTIVATE` 并放在后方。

只处理本次 `Popen` 创建的游戏进程的初始 UI 线程，不安装全局钩子，不切回其他应用，不改系统焦点策略或用户注册表。游戏以 `CREATE_SUSPENDED` 创建，先记录初始线程并尝试安装，再恢复；User32 队列尚未建立时仅重试该线程，安装失败则结束自己创建的游戏并报告失败。保护句柄由会话 worker 持有，退出时释放。普通前台启动完全跳过组件。

保护范围是初始 UI 线程；队列建立到钩子安装存在竞态，另建 UI 线程的引擎也需要重新验收。不能把通过某个版本的启动测试推及所有第三方窗口。实机用 `tests/manual_background_launch.py` 记录完整前台事件、HUD 就绪与后台截图，不能只比较启动前后两个窗口句柄。

组件为 x64，面向 x64 Windows 游戏与宿主 Python。完整开发构建使用 `python scripts/build_all_native.py`；已在 x64 MSVC 环境时可单独执行 `python scripts/build_window_activation.py`。DLL 和校验 manifest 随完整桌面包分发，不放进独立核心包。
