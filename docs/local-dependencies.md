# 本地目录依赖参考

主项目仍使用 `pyproject.toml` 管理项目；引用的 Addon 可以是直接从 MCS 导出的目录，**无需 `mcpy init`、无需 `pyproject.toml`，也无需 pip 安装**。

```toml
[project]
name = "my-addon"
version = "0.1.0"
dependencies = ["published-addon>=1.0"]

[tool.mcpywrap]
project_type = "addon"
target_dir = "./build"
local_dependencies = [
    "../shared-addon",
    "D:/Minecraft/common-resources",
]
```

有效目录至少包含一个行为包或资源包及其 `manifest.json` 或 `pack_manifest.json`，例如：

```text
shared-addon/
  behavior_pack/        # 也支持 behavior_pack_*、BehaviorPack*
    manifest.json
    sharedScript/
  resource_pack/        # 也支持 resource_pack_*、ResourcePack*
    manifest.json
```

第一版不支持把单独的行为包／资源包、地图根目录、普通源码目录作为本地依赖，也不支持同一 Addon 中多个同类型包。不必同时具备行为包和资源包。

相对路径相对于**声明它的项目目录**解析，与执行命令前的其他工作目录无关。目标目录存在 `[tool.mcpywrap]` 时，继续读取该项目的 Python 和本地依赖；否则视为叶节点。读取不会初始化、安装或修改目标目录。重复引用按真实路径去重（包含 Windows 大小写和目录链接）；循环引用会报告引用链。同名目录使用不同内部标识，避免链接覆盖。

```powershell
mcpy add --path "../共享 Addon"
mcpy add --path "D:/Minecraft/common-resources"
mcpy remove --path "../共享 Addon"

# 不带参数进入来源选择／直接依赖选择向导
mcpy add
mcpy remove
```

CLI 保留传入的相对或绝对写法，不根据包参数猜测路径。`--path` 不能与包参数同时使用；本地移除不接受 `--uninstall`。目录失效后仍可移除声明。非交互环境必须传入参数，否则返回非零退出码。`mcpy init` 的依赖收集也支持两种来源。

添加目录时会先验证结构和依赖图，无效或循环引用不会写入配置。其 Python 依赖未安装或版本不满足时，会显示警告及可复制的 `mcpy add "requirement"` 命令，允许保存本地引用，但**不会自动安装**。构建、运行、编辑器启动前会重新完整校验。Python 包仍通过当前工具环境的 pip 安装，安装失败不保存新增声明；环境标记为假的 requirement 不参与当前平台的依赖图，普通 Python 库也不会当成 Addon 加载。

### GUI 添加与移除

运行 `mcpy ui`，在“添加新依赖”选择“Python 包”或“本地目录”。包模式支持可编辑下拉框及补全，安装在后台执行，完成前禁用冲突操作；失败会保留输入并显示原因。

本地模式可输入路径或“浏览目录”，预览解析后的目录、包结构和将保存的路径。默认保存相对路径；跨盘保存绝对路径，也可勾选“保存为绝对路径”。**选择目录本身不保存，点击“添加依赖”才写入配置**。错误输入保留供修改。

依赖列表显示来源、声明和不可用状态，详细原因显示在提示中。移除本地依赖的确认框会说明仅移除引用，源目录保留。每次修改后刷新运行包集合，每次启动前重新校验；失效依赖可继续移除。配置更新只影响后续启动，不自动更改正在运行的游戏。

### 构建顺序与迁移

旧配置无需迁移，省略 `local_dependencies` 等同于空数组。只有本地依赖、没有 Python 包依赖的项目同样支持 `build/run/edit/dev`（地图项目仍不支持 `dev`）。本地引用只用于此工具，**不会自动成为可通过 pip 分发、安装或锁定的依赖**；分发时需自行安排资源和路径。

**行为变更：完整构建和增量构建现在都以主项目为最高优先级。** 顺序为子依赖先于引用者；同级先 Python 包列表、再本地列表，各列表按声明顺序处理，后处理者覆盖重复文件／合并键；主项目最后。共享子依赖只处理一次，采用稳定的依赖优先遍历。保留已有 JSON／语言文件合并规则及主项目 manifest。删除高优先级来源文件后，增量构建会恢复低优先级来源内容。

构建在清空输出前校验依赖及路径，拒绝输出覆盖源项目／源包或与依赖目录重叠。`dev` 监控主项目和解析到的所有依赖目录，修改依赖声明后需要重启监控。

`run/edit` 仍将依赖作为独立包链接／编辑器包路径传递，以上构建覆盖规则不代表游戏引擎自身的资源包加载优先级。Windows 优先使用符号链接，无符号链接权限时可使用目录 junction；复用已有同目标链接，保留其他项目链接，同名冲突明确报错。
