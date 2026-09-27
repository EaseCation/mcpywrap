# Git 项目依赖与框架预设

先用 bootstrap 检查 `git-dependencies` / `framework-presets`，或核对 `mcpy add --help`。本机开发流程使用公开CLI，不通过写内部缓存绕过解析或锁校验。

## 用户意图与命令

| 需求 | 命令 |
|---|---|
| 从Git获取已有Addon/带导出描述的项目 | `mcpy add --git <URL> --ref <提交或标签>` |
| 明确安装普通Python源码子目录 | `mcpy add --git <URL> --kind code --subdir src --target MyMod/SharedLib` |
| 准备预置框架与新入口 | `mcpy add --framework qumod --script-dir MyMod` |
| 使用QuMod官方Gitee来源 | 上述命令增加 `--source gitee` |
| 新建预置框架Mod | `mcpy mod --framework qumod --name MyMod --script-dir MyMod` |
| 克隆后恢复依赖 | `mcpy sync` |
| 移除Git项目依赖 | `mcpy remove --git <依赖名>` |
| 兼容旧代码库声明的移除 | `mcpy remove --library <代码库名>` |

首次省略 `--ref` 会解析当时的HEAD并保存完整SHA；不是每次构建追踪HEAD。重复添加同名来源默认保留版本，升级时明确提供 `--ref`。`--dep-name` 可指定稳定名称。GUI在 `mcpy ui` 中提供同样的Git依赖表单、QuMod快捷添加和同步按钮；Agent使用CLI，图形界面留给人工。

## 标准项目描述

项目持有 `[[tool.mcpywrap.git_dependencies]]`，每项声明 `name/git/rev`，可选 `subdir/kind/target`。持久化的rev必须是完整提交。

工具自动读取远端pyproject.toml的 `tool.mcpywrap.export`：

```toml
[tool.mcpywrap.export]
kind = "code"
path = "src"
target = "MyMod/SharedLib"
```

没有导出描述时可识别有效Addon。不能识别普通源码布局时，补充明确的子目录和目标，或让上游添加描述；不猜测安装任意目录、不执行上游安装脚本。

远端项目可以声明同样的Git子依赖；仓库内 `local_dependencies` 相对声明项目解析，必须留在该Git快照内。外部仓库用Git声明。工具检测循环、去重共同节点、校验源码及安装位置；不提供任意构建脚本执行、Git子模块自动安装或版本范围求解。Python `[project].dependencies` 仍属于工具环境，不等于游戏Mod依赖。

## 缓存和恢复

用户级缓存只保存已验证的不可变Git快照，各项目共享下载。项目 `.mcpy/` 保存独立注册节点和组装结果，游戏不直接加载共享源码。`MCPY_CACHE_DIR` 可覆盖缓存根目录；缓存路径不进入可移植锁文件。

提交项目配置、`mcpy-git.lock.json`、入口和业务代码；忽略 `.mcpy/`、`.runtime/`、build和dist。旧 `code_libraries` / `mcpy-code-libraries.lock.json` 保持兼容，也复用共享源码获取层。

只有add/sync获取远程内容。build/package/run缺少依赖时应显式sync，不临时pip安装框架。校验失败时不要删除锁来掩盖差异；保留原项目，按错误定位损坏缓存或不兼容声明。

## 框架边界

框架预设只是官方来源、推荐固定提交、导出布局和入口模板的数据。QuMod 1.4.3对应已验证源码提交，不代表存在同名官方Release。已有Mod入口保持原样；新Mod入口由预设生成。手工复制的框架目录会报安装位置冲突，不自行删除用户文件。

同一提交的下载可以共享，不代表不同Mod的框架运行时实例能合并。QuMod的QMain、系统与RPC命名依赖脚本根；每个独立Mod安装到自己的命名空间。移除声明不删除入口，随后检查业务导入。

验证依次检查CLI结果、锁与产物、真实游戏加载；构建成功不能证明游戏运行兼容，模拟测试不能代替多人或框架生命周期验收。
