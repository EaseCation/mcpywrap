# 两端安装与调用

本页用于首次设置局域网测试。区分三个地址：Windows 测试服务的 HTTP 地址、游戏服务器的 IP/端口、本机项目目录。
两台机器分别安装 CLI 和完整 Skill；bootstrap 返回的 command 只属于执行 bootstrap 的那台机器。
局域网流程使用 CLI 0.3.12+ 与 v0.3.12 配套 Skill。main 分支 Skill 可能领先 CLI；仍须检查下列能力，不能仅靠版本号或安装成功判定可用。

## Windows：准备执行端

在已登录、未锁屏的测试桌面中执行；下列 mcpy 代表 Windows bootstrap 返回的 command，路径有空格时 PowerShell 用 `& "<路径>"`。

```powershell
& "<skill目录>\scripts\bootstrap.ps1" -Local -RequireCapability serve
mcpy --local doctor --capabilities --json
mcpy --local doctor --json
mcpy --local serve
```

服务是持续的前台控制台程序，不传 --json，保持窗口打开。--local 避免已有 MCPY_REMOTE／项目配置把诊断送往其他电脑。
默认监听 `0.0.0.0:18765`，客户端填写 Windows 的实际局域网 IP，不填写 0.0.0.0。会话保存在 `.local/share/mcpywrap/remote`。
可用 `serve --host/--port/--data-dir` 调整；引擎 EXE／下载目录也在此设置。服务不注册后台任务或修改防火墙，按本机网络条件允许访问。
启动前必须在 Windows 设置 `MCPY_REMOTE_TOKEN`，并在 macOS 设置同一个值。远程服务允许在游戏客户端执行 Python，因此不再提供免认证启动；令牌和游戏的 `--mcs-auth` 无关。
需要 MCS 身份时，在 Windows 额外检查 `mcpy --local doctor --mcs-auth --json`，由用户打开并登录 MCS。
Git／可编辑安装可能缺少 CI 生成的桥接组件；使用包含组件且支持 serve 的发布构建，或在明确的源码开发任务中另行构建。不要通过安装旧发布版意外丢失 serve 能力。

## macOS：检查与调用

只需要 uv、CLI 和 Skill，不安装 MC Studio、游戏或 Qt。下列路径都是 macOS 路径；mcpy 代表本机 bootstrap 返回的 command。

```bash
uv run --no-project --python 3.12 "<skill>/scripts/bootstrap.py" --remote http://192.168.1.20:18765 --require-capability remote-client --require-capability network-sessions --require-capability screenshot --require-capability key --require-capability mouse
mcpy --remote http://192.168.1.20:18765 doctor --capabilities --json
mcpy --remote http://192.168.1.20:18765 --non-interactive connect 192.168.1.10 --port 19132 --detach --json
mcpy --remote http://192.168.1.20:18765 logs --session <id> --source game --tail 100 --json
mcpy --remote http://192.168.1.20:18765 screenshot --session <id> --output ./captures/game.png --json
mcpy --remote http://192.168.1.20:18765 stop --session <id> --json
```

bootstrap 的 --remote 只检查，不保存设置；上述每条命令显式携带地址，适用于彼此独立的 Agent 终端调用。
也可在能持续继承环境的进程中设置 MCPY_REMOTE，或在本机项目配置 remote_url。改变目录或开新进程后，重新确认实际路由，不假设之前的 export 仍生效。
登录任务额外使用 bootstrap 的 `--require-capability mcs-auth` 并在 connect/run 添加 --mcs-auth；检查 remote.mcs_auth，不以 macOS 本机 component_available=false 判失败。
游戏服务器必须从 Windows 可达；macOS 上的 localhost 不是 Windows 的 localhost。相同局域网里的 HTTP 服务地址和游戏服务器地址也可能完全不同。
init/add/build/package 仍操作 macOS 项目；只有配置 `[tool.mcpywrap.server] host/port` 的 run 可以远程执行，不上传或装配本地 Mod。
远程联机会话可用 `mcpy --remote <地址> runtime py --session <id> --code "1+1" --json` 执行客户端 Python；不支持服务端执行或远程热更。超时是结果未知，不自动重发。

## 返回字段与脚本参数

| 字段 | 应如何使用 |
|---|---|
| bootstrap.command | 本机 CLI 路径；辅助脚本 --command 使用它，不使用游戏 EXE |
| endpoint + session | 远程会话的组合身份；后续操作始终复用同一个服务地址和会话 ID |
| project | 调用端已有目录，用于本机配置和后续 --project |
| remote_project / executable | Windows 路径信息，不在 macOS 打开或执行 |
| log_path / engine_log_path | Windows 日志位置；客户端通过 logs --source game/engine/worker 读取 |
| image | 截图已保存到调用端的路径，可以直接查看 |

CLI 的 --remote/--local/--project/--non-interactive 放在子命令前；--json 可在子命令后。
game_window.py 的公共参数放在 screenshot/key/mouse 之前，后面的参数透传给该动作：

```bash
uv run --no-project --python 3.12 "<skill>/scripts/game_window.py" --project "/本机已有目录" --remote http://192.168.1.20:18765 --session <id> --command "/bootstrap返回的command" key SHIFT+W --hold-ms 500
```

本机世界只在 Windows 使用 `--local --project <Windows项目>`；远程不支持世界实例、实例删除、Qt 或编辑器。
远程启动必须 --detach，不能套用本机的前台等待方式。Windows serve Ctrl+C 停止所属游戏；macOS 调用结束不会自动停止会话。

## 鼠标与截图

- 截图是可见游戏客户区的物理像素，不包含标题栏；点击、移动、滚轮和拖拽需 --x/--y/--width/--height，参考最近截图。
- drag 增加 --to-x/--to-y/--duration-ms；--keys SHIFT 等修饰键在动作结束后释放。--button right/middle 选择按钮，默认 left；double-click 为双击。
- scroll --delta -120 向下滚一格，仍需上述坐标与宽高。relative --dx 100 --dy 0 --duration-ms 200 不需要绝对坐标，效果取决于输入模式和灵敏度。
- 触屏模式下可在视角区域 drag；相对位移 sent 不能单独证明转向成功。F11 切换模式、F3 循环调试层，按截图确认。
- 操作最长 60 秒，不支持跨请求一直按住。尺寸变化、遮挡、失焦或屏幕外时先恢复环境；foreground 错误由 Windows 端激活目标游戏，macOS 的 Computer Use 不能直接解决它。

## 找回与自动验证

busy 时用相同 endpoint 的 status --list 查询，不停止无关任务。启动超时可通过请求 ID 找回；`connect --request-id <原 ID>` 必须保持完全相同参数。
输入超时视为结果未知，先截图确认，不盲目重发。客户端断线后可重连查询；服务异常退出后，用相同 data-dir 重启可以找回所属会话。
会话／日志实际保存在 Windows data-dir。删除前停止游戏；PID 身份不匹配时拒绝操作，不改成按进程名终止。
远程自动验证用 `smoke.py --project <调用端目录> --remote <地址> --connect <服务器> --expect-log <标记>`，需要时追加 --mcs-auth。
Windows 本地世界用 `smoke.py --local --project <Windows项目> --game`；不要在远程配置下用 --game，也不要把纯连接目录用于默认打包流程。
smoke 默认等 90 秒，--expect-log 可重复；不提供标记只报告启动，并始终停止自己创建的会话。需要保持游戏或进行多步截图交互时，直接使用 CLI 会话命令。
