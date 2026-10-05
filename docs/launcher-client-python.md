# macOS 启动器客户端 Python

兼容启动器可在游戏进程建立后提供客户端 Python 请求队列。Python 尚未初始化时排队，准备好后执行；进入世界后继续使用同一客户端命名空间。服务端维持原 Safaia 通道。

这是已附加会话的执行能力，不代表 `mcpy run` 已经支持自动安装／启动 macOS 引擎。

```sh
mcpy --local --project /path/to/project runtime py --session SESSION --code 'value = 41' --json
mcpy --local --project /path/to/project runtime py --session SESSION --code 'value + 1' --json
```

也可使用 `--file` 读取 UTF-8 Python 2 脚本。返回 `stdout`、`stderr`、`value`、`error` 和 `request_id`。多行脚本以 `_result` 指定返回值。源码最大 32 KiB；输出沿用现有 mcpy 限制。

```sh
mcpy --local --project /path/to/project runtime py --session SESSION --file ./probe.py --no-wait --json
mcpy --local --project /path/to/project runtime py-result REQUEST_ID --session SESSION --json
mcpy --local --project /path/to/project runtime py-result REQUEST_ID --session SESSION --cancel --json
```

`--wait-until` 接收同一客户端命名空间中的无副作用布尔表达式。条件成立后代码只执行一次；尚未执行的请求可以取消。运行中的请求不能强行打断。

`queued`、`running` 不代表执行成功；`completed` 才包含完成结果。提交或等待结果不明时查询原 request_id，不重新提交有副作用的代码。进程内保留最近 64 个已查询完成的结果，退出后命名空间和历史失效。

适配器使用启动器的本地 Unix socket、进程绑定与私有目录权限，外层继续使用既有 mcpy 会话控制通道。旧启动器没有此能力时仍使用 Safaia。`--side server` 不使用新协议，也不接受 `--no-wait`／`--wait-until`。

`runtime install` 注入的 `mcpy.*` 仍仅限临时调试，不能成为业务 Addon 的依赖。

## JSON UI 定义重载

新运行包声明 `json_ui_reload_protocol=1`，在客户端 Python 中暴露 `_mcpy_launcher.reload_ui()`。普通开发请使用 `runtime reload ui`，以便先部署资源、核对会话并获得统一提示。此接口仅属于开发启动器，不能成为 Mod 的业务依赖。它异步重载定义，会使原控件失效；重新注册/创建界面与绑定回调由 Mod 原有逻辑完成，详见 [资源验收](macos-resource-reload.md)。服务端继续使用 Safaia，没有新增服务端协议。
