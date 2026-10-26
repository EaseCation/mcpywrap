# 测试入口

Windows 本地自动联机可选实机验收：

```powershell
python tests/manual_windows_local_groups.py --output test/lan-acceptance --engine-version 3.9.0.401155 --engine-version 3.10.0.436581
```

输出目录必须尚不存在；两次版本参数可相同。程序经公开 CLI 新建两个独立 Mod 项目、自动启动四端，验证每组世界/网络身份和服务端名单、实际客户端/服务端 Mod 系统加载、客机重启及另一组连接保留，最后停止自己创建的组。它需要完整 Windows 原生组件、对应引擎和可后台渲染的桌面；不进入默认 CI。`test_windows_lan.py` 使用人工指令夹具与模拟调用覆盖自动定位、歧义拒绝、写入回滚、菜单选择和取消；夹具不包含游戏二进制。明确未发送的只读探针争用可有限重试，未知执行结果不重放。

仓库通用开发与验证约定见 [CONTRIBUTING.md](../CONTRIBUTING.md)。默认自动化使用临时文件、真实有限子进程、模拟游戏调用端与回环服务，不启动真实游戏：

```text
python -X utf8 -m unittest discover -s tests -v
```

测试结果、环境信息和单次验收报告保存在 Git 忽略的 `.local-notes/`、`test/` 或 `.runtime/`，不放入 docs 或分发包。Windows 与 macOS 的实机结果分别记录；跳过不算通过。

## 共享核心与发行包

使用干净 checkout 和独立虚拟环境，按 [开发说明](../CONTRIBUTING.md) 同时安装 `./core` 与完整包。Windows 原生组件需要 Visual Studio x86/x64 C++ Build Tools，先运行 `python scripts/build_all_native.py` 再安装。没有 `py` 启动器时，可用 `uv venv --python 3.12 .venv` 创建环境，再通过对应解释器安装依赖。源码桥接未签名，不能据此判定正式登录签名链通过。

```text
python -m pip check
python -c "import importlib.util; from importlib.metadata import version; from mcpywrap_core.api import Core; assert version('mcpywrap') == version('mcpywrap-core') == Core().describe()['version']; assert importlib.util.find_spec('mcpywrap') is None"
python -m unittest discover -s tests -p 'test_core*.py' -v
python -m unittest discover -s tests -p test_distribution_layout.py -v
```

已有 checkout 的旧根目录 `mcpywrap.egg-info` 可能遮蔽新发行元数据；使用干净 checkout，或将旧生成目录移到工作区外留存后核对版本。

实际 wheel 安装与更新验证使用以下入口；将占位路径替换为待测产物、受支持旧版的 wheel 和忽略目录中的新报告文件：

```text
python scripts/verify_distributions.py --legacy-wheel <旧版完整包wheel> --output <安装报告.json>
python scripts/verify_core_release.py <核心wheel> --output <更新报告.json>
```

前者创建临时虚拟环境，检查核心单独安装、旧版原地升级后旧导入包被移除、完整依赖、卸载完整包后核心保留及重装后两条控制台命令恢复，不修改全局工具环境。Python 模块入口使用 `python -m mcpywrap_core`。后者使用真实核心 wheel，在独立进程中验证激活、更新、回滚与工程输出一致；临时 `+upgradeprobe` 版本仅作测试夹具。嵌入验证入口为 `embedded_upgrade_probe.py`，其公共请求文件只模拟已认证的发布信息，不能作为生产信任来源。构建和发布规则见 [RELEASING.md](../RELEASING.md)。

uv 工具安装应设置独立的 `UV_TOOL_DIR` 和 `UV_TOOL_BIN_DIR`，同时提供同版本核心与完整包，核对命令入口和安装资源；测试环境变量只作用于测试进程。

## Windows 编码与实机验证

在独立终端分别运行 GBK 与 UTF-8 全量测试，每次检查退出码：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '0'
$env:PYTHONIOENCODING = 'gbk'
python -m unittest discover -s tests -v
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
python -m unittest discover -s tests -v
Remove-Item Env:QT_QPA_PLATFORM, Env:PYTHONUTF8, Env:PYTHONIOENCODING
```

`PYTHONIOENCODING` 只控制标准输入输出。验证默认 GBK 文件编码还应检查 `locale.getencoding()`（Python 3.11+）及 Windows `GetACP()` 是否为 `936`；UTF-8 系统上只切换输出编码不能替代这项检查。直接捕获子进程原始字节，严格按目标编码解码，再断言中文和 JSON 的 Unicode 值；PowerShell 对重定向日志的转码显示不能作为字节兼容性证据。人类输出中 GBK 无法表示的字符允许转义。

实机使用包含中文和空格的独立工程目录，覆盖新建模组、本地/Git 依赖、构建、ZIP 导出、双端 Python 执行与热更、中文日志、截图及原实例重开。对带正确编码声明的 GBK/UTF-8 Python 模块，同时检查构建/归档字节与游戏内 Unicode 值；新业务源码仍建议统一 UTF-8。保存退出以重开后读回同一世界的数据为证据，Windows 进程终止的限制见 [运行后端](../docs/game-backends.md)。

需要焦点或原始键鼠的测试应单独运行，避免并行游戏启动或可见 Qt 测试干扰桌面和部署占用状态。结束后只清理自己创建的会话，保留原始证据。

后台启动验收使用 `python tests/manual_background_launch.py --output <新的证据目录> --engine-version <已安装版本>`，可重复指定版本。脚本创建独立项目/profile，记录 Windows 前台事件，验证后台启动至 HUD、默认截图不回退、桌面输入拒绝，并以显式前台启动作对照；最后停止自己的会话。前台对照会短暂聚焦游戏，profile 和报告保留。Mac 构建与验收见 [原生运行包补丁](../native/background_window/README.md)。

## 全局部署恢复

隔离实机脚本预置旧父项目双包链接，先验证完整冲突，注入发布后的启动失败以验证回滚，再迁移并用游戏内探针验证新代码。随后执行依赖 `0 → 1 → 0`、多世界共享、重复启动和删除测试实例后重新创建：

```text
python tests/manual/lifecycle_dependency_audit.py --output <新的隔离验收目录> --migration --engine-version <已安装版本> --mcs-download-path <下载目录>
```

该脚本只操作新建的测试项目和独立 profile，并保留命令响应、日志和结果。个人真实 profile 的历史链接不用于破坏性验收。产品契约见 [部署恢复](../docs/deployment-recovery.md)。

## 输入编排

`test_input_sequence.py`、`test_runtime_key_timeline.py`、`test_runtime_input.py` 验证时序、快照、取消、幂等和释放；兼容入口还需运行 `test_game_window_skill.py`、`test_mouse.py` 和真实回环协议测试 `test_remote.py`。

交互式 Windows 桌面显式设置 `MCPY_NATIVE_TESTS=1` 后可运行 `test_native_input_sequence.py`，只创建自己的接收窗口，检查 0/1/5/10/20 ms 的提交和接收顺序。`MCPY_INPUT_TEST_REPORT` 可指定新的报告路径；系统调度抖动应保留到结果中。

真实游戏使用 `manual_runtime_input.py --project <独立测试项目> --session <sid> --output <新JSON>`。需要已加载 HUD、快捷栏 8/9 为空并朝向无目标天空；会占用前台，随后恢复原选槽和朝向。`manual_runtime_key_timeline.py` 检查后台重叠按键、修饰键顺序及取消。脚本不会停止传入会话，由创建者清理。

## UI、玩家与世界

`test_runtime_ui.py`、`test_runtime_ui_outline.py` 验证快照、分组、输入归属和 UI 操作状态；`test_runtime_player.py` 验证选槽、移动、使用物品、队列和业务状态检查。可选实机程序与服务端夹具见 [runtime_controls](manual/runtime_controls/README.md)。只有客户端 completed 不足以证明服务端效果。

世界配置检查须覆盖保存后重开、生成器、种子、模式、难度、规则及实例隔离；各平台按自己的游戏环境执行。录制、后台采集等需要可见桌面的测试不进入默认执行路径，具体参数见对应 `manual_*.py --help`。

## 依赖与资源准备

`test_git_projects.py` 使用真实本地 Git 验证固定提交、导出、传递关系、缓存、锁和更新回退；游戏对第三方框架的兼容性需要单独确认。

`test_consumer_prepare.py` 覆盖本地/Git 准备入口、工具环境、只读计划、配置校验和生命周期；其中的独立 Skill 模板测试不依赖仓库外层示例。可选程序 `manual/consumer_prepare_acceptance.py --output <新目录>` 默认只验证资源准备，显式加 `--game` 才启动测试游戏，`--clients 2` 检查主机/客机准备次数。保留报告和世界，脚本只停止自己的测试会话。
