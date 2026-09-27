---
name: mcpywrap
description: 使用 mcpywrap 管理《我的世界》中国版 Addon/地图与依赖，在本机或局域网 Windows 端启动游戏、读取日志、截图和输入键鼠；支持 macOS 开发与 Windows 游戏联调。
---

# mcpywrap

使用公开 CLI；无需通读仓库 docs、CLAUDE.md 或源码。先确定项目操作发生在哪台机器、游戏在哪台 Windows 运行。

## 安装与前置检查

- Skill 文件夹和 CLI 分别安装，更新一端不会自动更新另一端。两台机器都复制完整 Skill，并在各自机器上检查 CLI。
- 使用已有 uv 运行 `uv run --no-project --python 3.12 "<skill>/scripts/bootstrap.py"`，无需假定 PATH 中存在 `python`；Windows 也可用 [bootstrap.ps1](scripts/bootstrap.ps1)。
- 默认复用已有安装；更换来源需 `--upgrade`，可选 `--version`、`--git-ref <完整 SHA>`、`--editable-path <本机目录>`。PowerShell 对应 `-Upgrade/-Version/-GitRef/-EditablePath`。
- 使用本机 bootstrap 返回的 `command` 执行后续 CLI；示例中的 `mcpy` 均指这个路径，不跨机器复用它。
- Windows 服务端：bootstrap 加 `--local --require-capability serve`，再用 `mcpy --local doctor --capabilities --json`。需要登录时额外检查 `mcs-auth` 组件并由用户登录 MCS。
- macOS 远程端：bootstrap 加 `--remote <地址> --require-capability remote-client --require-capability network-sessions`；截图／输入任务再要求 `screenshot/key/mouse`，可重复传入 `--require-capability`。
- 本机能力看 `local_capabilities`，Windows 服务能力看 `remote.capabilities`。`remote.ok=false` 时停止远程流程；组件具备不表示已登录、窗口已就绪或已进服。
- `bootstrap --remote` 只做检测，不保存路由。每次远程调用明确传 `--remote <endpoint>`，或确认当前进程确实继承了 `MCPY_REMOTE`；不依赖上一次终端调用的 export。
- 先检查相关 `--help` 和能力；不要把新版 Skill 配上旧 CLI 后猜参数。建议使用 CLI 0.3.7+ 与 v0.3.7 配套 Skill，依赖分类提示及原生文件校验从该版本提供；局域网细节见[远程测试](references/remote-testing.md)。

## 执行位置与参数

全局参数放在子命令之前：`mcpy --project "<本机已有目录>" --remote <地址> --non-interactive <命令> --json`。
路由优先级为 CLI → `MCPY_REMOTE` → 本机项目 `[tool.mcpywrap].remote_url`；`--local` 强制本机执行。远端失败不回退。

| 操作 | 执行位置 |
|---|---|
| init/add/remove/mod/modsdk/sync/build/package/dev/publish | 调用端本机，配置远端后也不迁移项目文件 |
| doctor/connect/status/logs/stop/screenshot/key/mouse | 配置的 Windows 服务；没有远端配置则在本机 |
| 配置服务器目标的 run | 本机校验项目与依赖，远端只连接服务器 |
| 本地世界 run、实例管理 | Windows 本机，明确使用 `--local`；远端不支持 |
| serve、edit、ui、mod --gui | Windows 本机；后面三个界面用于人工操作，不远程交接 |

`--project` 必须是调用端路径且目录已存在；纯连接不需要 init。远程实际会话保存在 Windows 的 serve 数据目录。
远程结果中的 `project/image` 是调用端路径；`remote_project/executable/log_path/engine_log_path` 是 Windows 信息。读取远程日志用 logs，不在 macOS 打开 Windows 路径。

## 项目工作流

有限命令使用 `--non-interactive --json`，检查退出码和 `ok/error/hint`；保留用户已选择的项目路径与配置。

| 任务 | 子命令 |
|---|---|
| 新建／接入 | `init --name demo --type addon` 或 `--type map` |
| 包依赖 | `add "package-name>=1.0"` / `remove package-name` |
| 本地 Addon 引用 | `add --path ../common` / `remove --path ../common` |
| 模板／SDK | `mod --name DemoMod` / `modsdk --version <版本>` |
| 构建／ZIP | `build` / `package`；地图要合并资源时用 `package --merge` |
| 同步／安装项目 | `sync` / `sync --install` |
| 为用户打开编辑器 | Windows 本机 `edit --detach`；启动不等于界面任务完成 |

初始化不覆盖已有配置、不隐式安装 SDK 或依赖。本地引用选 Addon 根目录，无需先初始化，不自动成为可分发包依赖。
`add`、`sync --install`、ModSDK 只安装于工具 Python；测试与正式游戏使用内置 Python，不读取依赖表或工具的 `site-packages`。
检查 JSON 的 `warnings`：“仅开发环境”的包不进入产物；仅识别出的 Addon 参与组装。需要的纯 Python 代码须随包携带并适配游戏；原生扩展和依赖外部安装的库不能直接用于游戏，不通过反复 pip 安装解决。
构建时主项目优先；检查 package 返回的 `artifact`。`dev` 持续输出文本，不用 JSON；依赖声明变化后重启监控。
检查 ZIP 的实际内容及游戏脚本加载日志；pip 安装、系统 Python 导入或构建成功都不能代替游戏验收。`publish` 的 PyPI 分发与游戏 ZIP 分发不同。
`publish --yes` 仅在用户请求真实上传时调用；卸载和实例删除也需相应明确选项。

## 游戏会话

Windows 用户在专用、已登录未锁屏的桌面运行 `mcpy --local serve` 并保持控制台打开；默认 `0.0.0.0:18765`，不加 `--json`。
远程首次设置按需读[远程测试](references/remote-testing.md)，不要把监听地址 0.0.0.0 当作客户端地址。

| 目标 | 启动命令 |
|---|---|
| Windows 本地世界 | `mcpy --local --project "<Windows项目>" --non-interactive run --no-gui --detach --json` |
| 远程临时服务器 | `mcpy --remote <Windows服务地址> --non-interactive connect <游戏服务器地址> --port 19132 --detach --json` |
| 远程项目目标 | `mcpy --remote <地址> --project "<调用端项目>" --non-interactive run --detach --json` |

固定游戏目标在项目 `[tool.mcpywrap.server]` 填 `host/port`。连接不装配本地 Mod，网络模式不支持 Map、`--new` 或世界实例 ID。
远程机器路径只在 Windows serve 参数中配置，客户端仅可覆盖 `--engine-version`；本机 connect 可使用原有引擎覆盖参数。
`MCPY_REMOTE_TOKEN` 是可选的服务访问令牌；`--mcs-auth` 才是本次游戏的 MCS 登录身份，二者互不替代。仅用户要求登录身份时添加该选项。

1. 保存启动返回的 `endpoint`（远程时）、`project`、`session`、进程身份和日志位置；后续操作始终绑定相同 endpoint 与 session。
2. 用相同全局参数调用 `status --session <id> --json`、`logs --session <id> --source game --tail 100 --json`；source 也可选 engine/worker。
3. `running/identity_provided/sent` 只说明对应阶段；Mod 加载、进服、交互效果分别用日志标记或截图确认。
4. 一次性测试结束 stop；用户要求保留时报告会话 ID。busy 时先列举，不停止不属于本任务的会话。

启动响应丢失用相同 endpoint 的 `status --list --json` 找回；输入超时不盲目重试。
只有本机运行可省略 detach/JSON 前台看日志：本机网络 Ctrl+C 停游戏，本机世界前台中断保留会话。远程始终用 detach。

## 截图、键鼠与验证脚本

```bash
mcpy --remote <endpoint> screenshot --session <id> --output ./captures/before.png --json
mcpy --remote <endpoint> key --session <id> SHIFT+W --hold-ms 2000 --json
mcpy --remote <endpoint> mouse click --session <id> --x 400 --y 300 --width 1280 --height 720 --json
```

本机操作把 remote 改成 `--local --project "<Windows项目>"`。兼容脚本 [game_window.py](scripts/game_window.py) 的 `--remote/--local/--project/--command` 放在 screenshot/key/mouse 之前。
截图保存到调用端、不覆盖文件；查看 `image` 确认画面。绝对坐标对应截图客户区宽高，尺寸变化后重新截图。
键盘支持组合与 VK/SC/E0；鼠标支持点击、双击、滚轮、拖拽和 relative。相对位移不保证触屏模式转向，必要时在视角区域拖拽；均以截图验证效果。
**F11** 切换鼠标／触屏模式，**F3** 循环调试层。切换后确认画面，测试结束恢复原状态，除非用户要求保留。
失焦、遮挡或释放失败时按[故障排查](references/troubleshooting.md)处理；不连续猜测输入。所有持有操作有时限并释放本次按键／按钮。
[smoke.py](scripts/smoke.py) 默认检查并打包；Windows 本地世界用 `--local --game`，远端用 `--remote <地址> --connect <服务器>`，均可显式加 `--mcs-auth`。
`--expect-log` 可重复，默认等 90 秒；未指定时只报告启动。脚本停止自己创建的会话，不用于需要保留游戏窗口的任务。
远程交互由 Agent 查看下载的图，再调用远程键鼠；macOS Computer Use 不会自动看到 Windows。Windows 本机复杂操作可按需使用环境已有的 Computer Use，Qt 页和编辑器仍留给人工。
