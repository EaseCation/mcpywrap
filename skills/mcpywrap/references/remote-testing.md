# Windows HTTP 远程执行端

用于设置服务、连接另一台 Windows 或排查跨机路由。单机连接游戏服务器不需要本页，直接读[网络会话](network-sessions.md)。

## Windows 准备服务

两端各自安装 CLI 和完整 Skill，命令路径不通用。安装方式见[安装与路由](setup.md)。Windows 需已登录、未锁屏的图形桌面，并有匹配 MC Studio 引擎；服务不会自动注册后台任务或修改防火墙。

```text
mcpy --local doctor --capabilities --json
mcpy --local doctor --json
mcpy --local serve
```

serve 为持续前台命令，不加 --json。默认监听 `0.0.0.0:18765`，客户端使用 Windows 的实际 IP，不能连接 0.0.0.0。可用 --host/--port/--data-dir 修改；游戏 EXE 和下载目录覆盖也由服务端配置。

默认需在 Windows 与调用端设置相同 MCPY_REMOTE_TOKEN。仅在用户明确选择无认证服务时用 `serve --no-token`；它忽略已有令牌，能访问端口的设备可执行客户端 Python。HTTP 令牌不是 MCS 游戏身份；登录流程见网络会话页。

Git/可编辑安装可能缺少 CI 生成的原生组件，按 doctor 的实际诊断处理，不自动安装旧版丢失当前功能。服务会话保存在 data-dir，默认用户目录下 `.local/share/mcpywrap/remote`。

## 调用端检查

调用端无需运行 Windows 游戏，也不通过本机桌面操作代替远端。mcpy 在某些平台安装时可能自带 Qt，但跨机命令不需要打开它。

```text
uv run --no-project --python 3.12 "<skill>/scripts/bootstrap.py" --remote http://192.168.1.20:18765 --require-capability remote-client --require-capability network-sessions --require-capability py
mcpy --remote http://192.168.1.20:18765 --non-interactive doctor --capabilities --json
```

需要输入或截图时再要求 unified-input / screenshot，不给单纯日志任务强加无关能力。bootstrap --remote 只检测；每次独立调用明确 --remote，或确认当前进程继承 MCPY_REMOTE。`remote.ok=false` 时先处理服务问题，不回退本机。

然后按[网络会话](network-sessions.md)启动和验证。游戏服务器必须从 Windows 可达；例如调用端的 localhost 不能自动成为 Windows 服务器地址。

| 路径/标识 | 含义 |
|---|---|
| bootstrap.command | 调用端 mcpy 路径，辅助脚本 --command 使用它 |
| endpoint + session | 远程会话身份，后续保持同一组合 |
| project | 调用端已有目录；项目命令和脚本仍在此运行 |
| remote_project、executable、log_path | Windows 路径，不在调用端打开/执行；日志通过 logs 获取 |
| image、video、images | 下载完成后的调用端路径，可查看 |

远程仅支持网络单会话，不支持本地世界/实例管理、双客户端、Qt/MCEditor、服务端 Python、本地资源部署或 reload/watch。Windows 本地世界和 macOS 本地 Addon 均使用各自 --local，不把远程接口当另一台机器的文件同步工具。

Windows serve 退出会处理其所属游戏；调用端命令结束不自动停止远程会话。需持续服务时保持服务进程与图形会话。

## 观察与恢复

游戏输入见[统一输入](runtime-input.md)，Windows 截图/录制见[画面采集](capture.md)。操作对象必须绑定同一服务和 session；失败不转用调用端键鼠或默认桌面截图。

响应丢失先同 endpoint 的 status --list 找回。服务异常退出后使用原 data-dir 启动可查找所属会话；无法核对 PID 身份时不按进程名批量终止。输入 unknown 查原 operation_id，不能以 HTTP 请求超时推断操作未执行。

兼容旧自动化时，`scripts/game_window.py` 的 --project/--remote/--session/--command 放在动作之前，动作后的参数透传。新任务优先公开 CLI；旧 key/mouse/input-sequence 的写法见[兼容输入](input-writing.md)。
