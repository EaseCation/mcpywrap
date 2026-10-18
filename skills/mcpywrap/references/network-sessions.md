# 连接外部服务器与可选登录身份

用于外部游戏服务器，不用于创建本地世界。游戏服务器地址/UDP 端口与 Windows 远程服务的 HTTP endpoint 是不同地址；本机 localhost 不代表远程 Windows 的 localhost。

## 选择目标

```text
mcpy --local --project <已有会话目录> --non-interactive connect <游戏服务器> --port 19132 --detach --json
mcpy --remote <Windows服务HTTP地址> --project <调用端目录> --non-interactive connect <游戏服务器> --port 19132 --detach --json
```

connect 只用项目目录存放/定位会话，不要求 init，也不读取 server 目标等项目配置。远端必须 --detach；本机为 AI 调用也使用 detach。首次跨机使用先读[远程执行端](remote-testing.md)。

项目长期固定目标时才配置：

```toml
[tool.mcpywrap.server]
host = "127.0.0.1"
port = 19132
```

随后可 `mcpy --local --project <项目> --non-interactive run --no-gui --detach --json`；远端改为 --remote 并保留 detach。配置 server 的 run 会校验本机项目/依赖，但不装配、上传或安装本地 Mod，也不执行 before_run。网络模式不接受 Map、--new、世界创建选项或实例 ID。

## 平台与身份

| 执行端 | 能力边界 |
|---|---|
| Windows 本机或 HTTP 服务 | 网络会话；可按用户需求显式传 --mcs-auth |
| Apple Silicon macOS | 只连接允许无认证开发客户端的服务器；运行包须支持网络协议，见[macOS 平台](macos-local.md) |
| 两个本机客户端 | 读[双客户端](dual-clients.md)，不能把单会话参数或同一账号复制当多玩家支持 |

`--mcs-auth` 是每次启动的游戏身份选择，不写入 server.auth。仅用户需要登录身份时使用；由用户在 Windows MC Studio 登录，先核对 `doctor --mcs-auth --json` 的组件/策略结果。MCPY_REMOTE_TOKEN 只保护 HTTP 服务访问，与游戏身份无关。

组件存在不等于已登录，identity_provided 不等于服务器已接受认证。身份过期重新获取并新建会话；没有自动刷新，不通过复制账户文件或改设备身份解决。

远程 EXE/下载目录由 Windows serve 配置；调用端可按帮助覆盖完整 engine-version，不传 Windows 文件路径当本机项目。公开服务器是否接受此开发客户端由其认证和协议决定，不能从工具启动成功推断。

## 查询、调试、退出

保存 endpoint/project/session，用相同目标执行 status、logs --source game|engine|worker 和 stop。进程 running 不证明进服；按日志、HUD 和业务状态核验。macOS 单会话 connection_verified 只表示曾观察到 HUD，不是持续在线探活或身份认证。

网络会话只提供客户端 Python。`runtime py --session <sid> --side client --file <本机探针.py> --json` 的结果处理见[运行时调试](runtime-debug.md)；输入使用[统一输入](runtime-input.md)。服务端 Python、本地 Mod 热更和外服服务端部署不属于网络会话能力。

响应丢失先 status --list 找回，不重复创建会话；有 request_id 时按原请求和相同参数查询/重试，不能用新 ID 盲目重发有副作用操作。一次性测试停止自己创建的会话，用户要求保留则报告目标。

只需连接、探针和日志并自动结束本次测试时，可用 `scripts/smoke.py --project <目录> --command <本机mcpy> --local --connect <服务器> --port 19132 --expect-log <标记>`；远程替换 --local 为 --remote。该模式不执行 package，不验证本地资源分发；没有标记/探针只证明进程启动。
