# 共享核心、双发行包与宿主接入

一个仓库、一套工程实现，提供共享核心与完整桌面工具两个发行包。两包版本同步，完整包精确依赖同版本核心。

## 安装与文件归属

| 发行包 | 安装方式 | 唯一拥有的内容 |
| --- | --- | --- |
| 完整桌面工具 `mcpywrap` | `pip install mcpywrap` 或 `uv tool install mcpywrap` | `mcpy` / `mcpywrap` 控制台脚本、宿主资源 `mcpywrap_assets` |
| 共享核心 `mcpywrap-core` | `pip install mcpywrap-core` 或 `uv pip install mcpywrap-core` | 实现 `mcpywrap_core`、固定启动支撑库 `mcpywrap_host` |

完整包精确依赖 `mcpywrap-core==同一版本`，并默认安装 Qt、监控、发布和消费者准备等完整依赖。核心包只要求 click、packaging、tomli、tomli-w，它们均有纯 Python 实现；额外可选 `mcpywrap-core[watch]`、`mcpywrap-core[prepare]`。

核心库不拥有控制台脚本，避免安装/卸载完整包时争夺 `mcpy` 文件。需要最小环境中的命令调试，可使用 `python -m mcpywrap_core`；执行的还是同一 CLI 实现，不维护第二套命令逻辑。

0.5.x 的完整包拥有 `mcpywrap/` 下全部实现。核心使用独立的 `mcpywrap_core/`，pip 安装核心后再卸载旧完整包不会删除新核心。完整包不提供 `mcpywrap` Python 导入包；宿主接入使用 `mcpywrap_core.api.Core`，内部测试使用实现所属的 `mcpywrap_core.*`。发行包名、控制台命令和项目 `[tool.mcpywrap]` 配置保持原名。

## 目录

```text
pyproject.toml / setup.py          完整包元数据，版本及核心依赖从唯一版本源读取
core/
  pyproject.toml                  核心包元数据
  mcpywrap_core/
    _version.py                   唯一发布版本号
    api.py / operations/          公共工程入口与编排
    dependencies.py / builders/   依赖、组装等唯一实现
    commands/ / ui/ / runtime/    同一 CLI、界面与运行逻辑，重依赖按需加载
    host.py                       平台能力接口
  mcpywrap_host/                  固定启动器和核心版本管理，不实现工程规则
desktop/
  mcpywrap_assets/                Windows 原生组件，构建生成，不进核心 wheel
scripts/                          构建、版本、发布检查、原生组件工具
tests/                            跨平台、兼容、包归属与升级检查
```

核心中的桌面相关 Python 文件不等于强制安装其依赖；按需导入避免核心环境加载 Qt、watchdog、rich、psutil。没有复制一份 Android 构建器。新命令和能力继续添加到同一实现。

源码开发安装：`pip install -e ./core -e .`。应同时安装同一 checkout 的两包，避免从索引解析到不匹配或尚不可用的核心版本。开发环境与构建流程见 [CONTRIBUTING.md](../CONTRIBUTING.md)，可复用测试入口见 [tests/README.md](../tests/README.md#共享核心与发行包)。

## 同一 API 与宿主能力

当前公共操作为 `resolve / build / package / sync`。现有 CLI 的 build/package/sync 调用它们；运行和调试模块保持原实现，尚未全部纳入该操作表。

```python
from pathlib import Path
from mcpywrap_core.api import Core
from mcpywrap_core.host import HostServices

core = Core(HostServices(
    python_executable=None,
    allow_processes=False,
    lock_directory=Path(app_private_files) / 'locks',
    cache_directory=Path('/sdcard/mcpy/cache'),
))
result = core.execute('build', '/sdcard/mcpy/projects/example', merge=False)
```

`Core.request()` 是传输无关的结构化调用，不是公开网络服务器。HTTP/WS/RPC 宿主先验证授权，将注册的项目 ID 解析为本机路径，再交给核心。PRoot 的 `/workspace/foo` 不直接当成 Android 路径。

`HostServices` 提供命令执行、脚本运行、项目工具环境、缓存、锁和事件能力。默认宿主沿用桌面子进程实现；嵌入宿主缺少能力时明确拒绝，不尝试把 `app_process64` 当 Python，也不改用外部核心。项目配置、hooks 顺序、版本约束、依赖合并规则始终共用。

源码、构建产物、存档与日志仍属于公共工作区；私有锁不能阻止外部编辑器直接改文件。正式宿主任务服务需要序列化修改任务，并管理取消、输入变化和一致性发布。

## 版本与发行契约

版本唯一来源为 `core/mcpywrap_core/_version.py`。两个发行包始终使用同一版本，完整包的核心依赖由该版本自动生成；Python 包版本、宿主协议版本与 Android App 版本分别管理。

构建输出为 `dist/core/` 与 `dist/desktop/`，分别包含可独立重建的 sdist 和 wheel。CI 检查版本、依赖精确绑定、源码完整性和文件归属互不重叠。核心 wheel 本身就是 App 的更新载荷，无需从完整 wheel 裁剪生成。

发布先上传核心，等待两个核心文件在 PyPI 可见且摘要一致，再上传完整包。重试只补缺失文件：相同文件名若摘要不同必须换新版本，不允许盲目 `skip-existing`。PyPI 不提供双包原子发布；完整流程见 [RELEASING.md](../RELEASING.md)。

## 不更新 APK 的核心更新

App 固定 Python/JNI 运行时与 `mcpywrap_host` 启动器，仅更换 `mcpywrap-core` 的 Python 模块。宿主先验证发布来源，再提供可信的版本与 SHA-256：

```python
from mcpywrap_host import CoreStore
store = CoreStore(app_private_files / 'core-releases')
release = store.stage(downloaded_core_wheel,
                     expected_sha256=trusted_release.sha256,
                     expected_version=trusted_release.version)
```

安装不导入候选代码，也不运行 pip/setup.py。它检查包名、版本、摘要、Python 版本、基础依赖、核心/宿主契约、路径、解压大小及原生载荷。`mcpywrap-core` wheel 中的 bootstrap 不覆盖 App 已固定的 bootstrap。

切换必须在尚未导入核心的新工作进程进行：

```python
def configure(Core):
    from mcpywrap_core.host import HostServices
    return Core(HostServices(python_executable=None, allow_processes=False,
                            lock_directory=app_private_files / 'locks'))

core = store.activate(release['sha256'], configure=configure,
                      health_check=check_core_health)
```

通常启动使用 `load_selected(configure=configure)`；返回 None 时，导入随 App 提供的 `mcpywrap_core.api.Core` 并按同样方式配置。激活成功才更新选择记录。失败保留旧选择；已安装文件后来损坏则为下一次启动选择上一版。禁止在运行中的解释器热替换模块；`rollback()` 也只影响下一核心进程。

Python 包版本与宿主协议版本、Android App 版本独立。兼容的规则改进可直接更新核心；Python ABI、基础依赖或宿主协议不满足时拒绝升级并保留旧版。基础依赖的成组更新、正式 App 更新 UI、后台服务、可信更新目录及外部 mcpy 的 App 后端路由尚未接入。

核心 API、独立安装、旧版升级及更新回滚的测试方式统一维护在 [测试入口](../tests/README.md#共享核心与发行包)。测试夹具中的发布信息不能用作生产信任来源。
