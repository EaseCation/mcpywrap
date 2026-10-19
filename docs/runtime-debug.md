# 运行时调试：维护者入口

用户命令、端侧、结果状态和热更限制统一维护在内置 Skill 的 [运行时调试](../skills/mcpywrap/references/runtime-debug.md)。启动/世界/部署规则见 [本地生命周期](../skills/mcpywrap/references/local-development.md)，多人协调见 [双客户端](../skills/mcpywrap/references/dual-clients.md)。本页不再复制另一套操作说明。

实现定位：`mcstudio/runtime_debug.py` 管理游戏调试请求；`mcstudio/hot_reload.py` 和 `runtime/groups.py` 处理单会话/组更新；`runtime/watch.py` 观察源码事件；实际运行文件写入经 `runtime/deployment.py`。worker 按真实进程身份建立通道和归属，旧 worker 的能力不能由新版 CLI 推定。

Windows 服务端/客户端通道与 macOS 客户端队列实现不同，调用者使用公共能力查询。原生平台资源适配见 [macOS 资源实现说明](macos-resource-reload.md)，通用回归入口见 [开发与验证](../CONTRIBUTING.md)。
