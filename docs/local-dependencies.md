# 复用本地 Addon

已有的 Addon 可以直接作为依赖，不需要先初始化或安装。

```powershell
mcpy add --path "../shared-addon"
mcpy remove --path "../shared-addon"
```

请选择 Addon 根目录，例如：

```text
shared-addon/
  behavior_pack/manifest.json
  resource_pack/manifest.json
```

可以只有行为包或资源包；目录名也支持工具识别的 `BehaviorPack*`、`ResourcePack*` 等名称。
不支持直接引用单个包目录、地图、普通源码目录，或同一 Addon 中多个同类型包。

引用保存在 `tool.mcpywrap.local_dependencies`，相对路径以声明它的项目为基准。
移除引用不会删除源目录。已有 mcpywrap 项目的子依赖会一并解析；循环依赖或失效路径会报错。

`mcpy add "package-name>=1.0"` 在 mcpy 工具环境安装包。只有能从本地安装来源解析出有效 Addon 的内容参与组装；
普通 Python 包或未识别到 Addon 内容的 wheel 标记为“仅开发环境”，不会复制 `site-packages`。
本地路径不会自动转换为可分发的包依赖；共享项目时需同步引用目录。
本地引用的包依赖未安装时，按警告显式安装；版本约束与环境标记检查的是工具 Python，不代表游戏兼容性。

测试和正式游戏都使用游戏内置 Python，不读取 `dependencies`，不自动安装或加载其他 Mod。
需要的纯 Python 代码及资源必须包含在 Addon 中，并适配游戏解释器、标准库及 ModSDK。
游戏包内的 `.pyd`、`.dll`、`.so`、版本化 `.so.*`、`.dylib` 会在构建、打包、运行和编辑前报错，
不再静默过滤；`dev` 检测到这类文件时保留原输出，移除问题文件后可恢复更新。
开发工具可以使用二进制包，只要这些文件不放在游戏包中。依赖外部安装步骤或系统环境的库也不能直接用于游戏；
当前校验不会分析所有 Python import，仍需检查 ZIP 内容和实际游戏日志。

验收解包产物时，避免同时加载相同 manifest UUID 的源码包与产物，防止游戏选中旧内容。

构建时主项目优先于依赖；同级依赖按声明顺序处理，后者覆盖重复内容。
这不代表游戏运行时的资源包优先级。修改依赖声明后重启 `mcpy dev`。

遇到结构错误先核对目录和清单；查看参数使用 `mcpy add --help`。
