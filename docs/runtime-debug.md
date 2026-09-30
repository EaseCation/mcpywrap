# 游戏运行时 Python 与热更

`mcpy runtime` 控制已启动的游戏会话。其中 `runtime py` 通过 MC Studio 游戏内置的 Safaia 调试协议执行 Python 2。Windows 会话 worker 按游戏 PID 定向发现连接，并把返回日志关联到请求 ID。无需加载调试 Mod；普通游戏日志仍保留在会话的 `game.log`。

```powershell
mcpy --local --project D:\mods\demo run --no-gui --detach --json
mcpy --local --project D:\mods\demo runtime py --session <id> --side client --code "1+1" --json
mcpy --local --project D:\mods\demo runtime py --session <id> --side server --file .\probe.py --json
mcpy --local --project D:\mods\demo runtime reload python --session <id> --file .\behavior_pack\MyMod\config.py --json
mcpy --local --project D:\mods\demo runtime reload python --session <id> --module MyMod.server.logic --side server --json
mcpy --local --project D:\mods\demo runtime reload ui --session <id> --json
mcpy --local --project D:\mods\demo runtime watch --session <id>
```

本地世界支持客户端和服务端脚本，远程联机会话仅支持客户端。远程 `serve` 必须配置 `MCPY_REMOTE_TOKEN`，调用端使用相同令牌。`--file` 在调用端读取 UTF-8，不向 Windows 发送文件路径。

`state=completed` 表示脚本返回；`failed` 包含异常；`unavailable` 表示连接未就绪；`unknown` 表示等待超时，代码可能继续运行，不能自动重试。同一会话的前一个未知请求结束前会拒绝新的脚本。执行结果限制 256 KiB，代码限制 32 KiB。

Python 热更要求模块已加载，使用当前项目或已装配依赖包内的源码更新该模块命名空间。它不会自动重建已存在的类实例、事件订阅或游戏世界状态。`runtime watch` 只对成功组装的变更触发热更；停止监控不停止游戏。顶层 `py`、`reload` 和 `dev --reload-session` 暂时保留为旧脚本兼容入口，不再出现在常规帮助中。

从0.3.13起，手动Python热更可显式`--side server`；默认client只适合客户端或不执行端侧API的纯逻辑模块。服务端模块在client上下文重新初始化可缓存无效组件，不能只检查模块执行成功。资源热更仅client；watch仍沿用client默认值。

worker启动时在现有control.json声明`python_reload_sides`。服务端热更在建立执行连接前检查该字段；旧worker缺失能力时不会收到源码，须正常保存并重启会话。客户端热更保留旧worker兼容。返回端侧与请求不一致，或成功结果缺失端侧时，结果为unknown／reload_side_mismatch；可能已有副作用，不能自动重试。更新CLI不会替换正在运行的worker。

## 实机结果

2026-09-30 在隔离测试世界验证：

| 引擎 | Python 执行 | Python 模块热更 | JSON UI | Particle | Material | Shader |
|---|---|---|---|---|---|---|
| 3.9.0.401155 | 客户端/服务端通过 | 修改后游戏内读取到新值 | 快捷键已投递，效果无回执 | 未验证 | 不提供接口 | 禁用，未验证安全性 |
| 3.10.0.420447 | 客户端/服务端通过 | 手动及 `dev` 监控均读到新值 | 快捷键已投递，效果无回执 | 接口返回成功 | 不提供接口 | 单文件接口使游戏失去响应，已禁用 |

JSON UI 的 `triggered` 只代表向目标窗口投递原生 Ctrl+R；必须用画面或业务日志确认实际界面变化。Shader 在上述版本返回 `unsupported`，不会冒险自动调用。其他引擎版本仍需先用隔离测试世界验证资源重载接口。
