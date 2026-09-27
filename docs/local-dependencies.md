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

需要发布的 Python 包使用 `mcpy add "package-name>=1.0"`。本地路径不会自动转换为可分发的包依赖；
共享项目时需同步引用目录，或把组件发布为 Python 包。本地引用的包依赖未安装时，按警告显式安装。

构建时主项目优先于依赖；同级依赖按声明顺序处理，后者覆盖重复内容。
这不代表游戏运行时的资源包优先级。修改依赖声明后重启 `mcpy dev`。

遇到结构错误先核对目录和清单；查看参数使用 `mcpy add --help`。
