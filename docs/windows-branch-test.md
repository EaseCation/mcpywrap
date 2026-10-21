# Windows 分支验收：0.6.0 双发行包

此分支尚未发布 PyPI。请在独立 checkout 测试；`pip install mcpywrap` 仍会安装当前已发布版本。

在已有仓库运行：

```powershell
git fetch origin
git worktree add ../mcpywrap-core-test origin/codex/shared-python-core
cd ../mcpywrap-core-test
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe scripts/build_all_native.py
.\.venv\Scripts\python.exe -m pip install -e ./core -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\mcpy.exe --version
```

原生组件构建需要 Visual Studio 的 x86/x64 C++ Build Tools。源码构建的组件没有正式发布签名，登录签名链不属于这次源码验收的成功判据。

检查两包版本和旧导入兼容：

```powershell
.\.venv\Scripts\python.exe -c "from importlib.metadata import version; import mcpywrap.api,mcpywrap_core.api; print(version('mcpywrap'), version('mcpywrap-core')); assert mcpywrap.api is mcpywrap_core.api"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_core*.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_distribution_layout.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

两包应同为 `0.6.0`。旧 `mcpywrap.*` 和新 `mcpywrap_core.*` 不应产生不同的模块或类对象。

人工流程建议在新测试工程里检查：项目界面、新建模组、本地/Git 依赖、构建、ZIP 导出、启动游戏、改源码后重开或热更、保存退出。共享核心没有改变项目 `pyproject.toml` 的 `tool.mcpywrap` 配置名称。

如需验证实际安装包和旧版升级，而不只是 editable 安装：

```powershell
.\.venv\Scripts\python.exe scripts/build_distributions.py
.\.venv\Scripts\python.exe scripts/check_release.py --require-native
.\.venv\Scripts\python.exe -m pip download --no-deps mcpywrap==0.5.8 --dest .local-notes/legacy
.\.venv\Scripts\python.exe scripts/verify_distributions.py --legacy-wheel .local-notes/legacy/mcpywrap-0.5.8-py3-none-any.whl --output .local-notes/install-report.json
```

安装验收脚本创建自己的临时虚拟环境，验证核心单独安装、0.5.8 原地升级、完整包默认依赖、卸载完整包后核心保留、重装后命令恢复，不修改全局 uv tool 或原有项目环境。

uv 工具安装也可以在专门的测试工具目录验证：

```powershell
$env:UV_TOOL_DIR = "$PWD/.local-notes/uv-tools"
$env:UV_TOOL_BIN_DIR = "$PWD/.local-notes/uv-bin"
uv tool install --with ./core .
& "$env:UV_TOOL_BIN_DIR/mcpy.exe" --version
```

这些设置只用于当前 PowerShell 会话的测试目录。正式发布后普通用户仍使用 `uv tool install mcpywrap`，不需要额外参数。
