# 已有会话：Python 执行、热更与监控

本页从已选定 session 开始，不负责创建世界。先查 status 确认会话，以及本地 `runtime capabilities --session <sid> --json`；远端用 doctor --capabilities。组成员若要更新代码先读[组热更](dual-clients.md#更新代码)，不能用单会话入口绕过组协调。

## 执行 Python 2

```text
mcpy --local --project <项目> --non-interactive runtime py --session <sid> --side client --code "1 + 1" --json
mcpy --local --project <项目> --non-interactive runtime py --session <sid> --side server --file <服务端探针.py> --json
```

code/file 二选一；文件在调用端按 UTF-8 读取，远程传内容而不是路径。本地世界可执行客户端与服务端；网络/客机仅客户端。用正式 ModSDK 或项目已有函数验收，不把临时 mcpy.* 写进业务代码。

| 结果 | 处理 |
|---|---|
| completed | 检查 side、stdout/stderr、value/error；效果仍需断言 |
| unavailable | 通道/脚本系统尚未就绪，先查会话和日志 |
| failed | 读取异常；可能有部分副作用，不自动重试 |
| unknown | 原代码可能继续执行；保留原请求、查状态/日志，不换 ID 重发 |

默认同步执行。只有当前会话 `python.client_queue=true` 时才使用客户端 `--no-wait` / `--wait-until <无副作用表达式>`，并用 `runtime py-result <request_id> --session <sid> --json` 查询；--cancel 仅取消尚未执行的客户端请求。远端和服务端不支持这组队列选项。更新 CLI 不会替换已运行 worker。

需要比进程存活更强的只读就绪确认时，可在客户端查询：

```python
try:
    import mod.client.extraClientApi as api, gui
    _result = api.GetLevelId() not in (None, -1, '-1') and gui.get_top_screen() == 'hud_screen'
except (ImportError, AttributeError):
    _result = False
```

该探针只证明客户端进入 HUD。服务端初始化、多人同步和玩法效果分别验证。

## 单会话热更

```text
mcpy --local --project <项目> runtime reload python --session <sid> --module MyMod.client.logic --side client --json
mcpy --local --project <项目> runtime reload python --session <sid> --module MyMod.server.logic --side server --json
mcpy --local --project <项目> runtime reload ui --session <sid> --json
mcpy --local --project <项目> runtime watch --session <sid> --side client
```

Python reload 可用项目内 --file 或 --module，不能同时给。模块必须已加载；执行源码不会重建现有类实例、订阅或游戏状态。服务端初始化模块明确用 server，不能用默认 client 试错。单会话 reload 不接受 both；watch 可显式 both，但只适合可在两端安全执行的公共模块。

热更前仍经部署保护；有未授权的其他读者或依赖/包身份变化时按错误处理，不能让失败退化为直接复制运行目录。runtime watch 不执行项目预处理钩子，文件删除和结构变化按提示重新运行。dev 是离线构建，二者不能互换。

watch 是持续文本命令，不加 --json；中断只停止监控，游戏继续运行。未知、partial 或 reload_side_mismatch 不重复注入有副作用模块；先核对实际成员、端侧、日志和能力。

## 资源重载

资源仅在客户端；ui 无需文件，particle/material/shader 需要 --file 指向项目内目标。先检查当前会话能力与 reason，收到 unsupported 不换隐蔽接口绕过。

- JSON UI 的 triggered/effect_verified=false 表示请求已投递；重新打开界面，按 Mod 的正常逻辑创建控件并绑定回调，检查实际文字和画面。旧节点句柄可能失效。
- 当前 macOS 开发包不会因该重载触发 UiInitFinished；不要全局伪造事件或把调试 `_mcpy_launcher` 当作业务 API。新资源/复杂继承仍可能需重开世界。
- Windows 3.9.0.401155 / 3.10.0.420447 的 Shader 重载禁用，Material 没有对应接口。macOS 的协议/版本差异见[平台页](macos-local.md)，不根据名称相似假定接口存在。
- 组资源热更当前明确拒绝；主机文件更新不等于客机下载缓存更新，详见双客户端页。

要操作 UI/玩家而非修改代码，直接用[统一输入](runtime-input.md)；无需为普通输入阅读热更实现。
