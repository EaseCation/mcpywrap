# Git 依赖与 QuMod 快捷添加

本文件用于Git仓库依赖、QuMod接入、克隆恢复及版本管理。使用公开CLI；不要手写内部缓存或修改已注册快照。

## 先检查能力和项目

- bootstrap 检查 `git-dependencies`；需要QuMod快捷操作时同时检查 `framework-presets`。两者是CLI能力名称，UI统一称“Git依赖”。也可核对 `mcpy add --help`，不根据版本号或本机恰好有库文件推断支持。
- 使用bootstrap返回的 `command`。源码尚未发布时，选择包含功能的已知源码目录／提交，不假设PyPI最新版本已经具备。远程提交必须实际可获取；仅本机的改动用bootstrap的 `--upgrade --editable-path <源码目录>`，不要把本地未推送SHA当远程安装来源。
- 确定项目目录已存在，读取其 `pyproject.toml` 中的依赖声明。新空目录先初始化；已有配置不重做init。保留用户指定的来源、提交、别名和Mod脚本目录。
- 下文 `mcpy` 代表实际CLI路径；对Agent调用使用 `--project "<项目>" --non-interactive`，有限命令加 `--json`。

## 根据意图选择操作

| 用户需求 | 操作 |
|---|---|
| “刚克隆项目，准备依赖” | `sync`；不重复add，不安装QuMod到site-packages |
| “给项目加入QuMod” | `add --qumod --script-dir MyMod` |
| “从这个仓库加入一个依赖” | `add --git <URL>`，保留用户提供的ref和布局参数 |
| “引用本机已有Addon” | `add --path <Addon根目录>` |
| “升级／回退Git依赖” | 对同一来源和别名再次add，明确传 `--ref` |
| “移除Git依赖” | `remove --git <声明中的name>`；不用仓库URL或Python包名代替别名 |

GUI对应 `mcpy ui` → Git依赖表单，其中“一键添加 QuMod”只是快捷按钮；下拉菜单可选来源和指定脚本目录。AI执行CLI，不为使用这些能力去操作Qt向导。

## 三种常用流程

### 新建基础 QuMod 项目

先建立用户选择的空目录，然后：

```text
mcpy --project "<项目>" --non-interactive init --name demo --type addon --json
mcpy --project "<项目>" --non-interactive add --qumod --script-dir DemoScript --json
mcpy --project "<项目>" --non-interactive package --json
```

快捷命令为新脚本目录生成 `modMain.py`、Server.py、Client.py及初始化文件，并声明、同步外部框架。无需先执行原生 `mod --name`；已有入口时不会自动改成QuMod。

省略script-dir时：唯一已有Mod自动选择，没有入口则创建MyScript，多个Mod报错要求明确选择。根据项目目录判断，不随意把多个Mod合并到一个框架实例。

需要沿用模板命令时，可用 `mod --framework qumod --name MyMod --script-dir MyMod`，但该命令要求目标目录尚不存在。`add --qumod`与`add --framework qumod`是同一预设，不要同时传两者。

### 给已有项目添加普通 Git 依赖

有有效Addon结构或标准导出描述：

```text
mcpy --project "<项目>" --non-interactive add --git "<URL>" --ref "<用户选择的提交或标签>" --dep-name shared --json
```

无描述的纯代码项目，先检查源码布局，再明确安装位置：

```text
mcpy --project "<项目>" --non-interactive add --git "<URL>" --kind code --subdir src --target MyMod/SharedLib --dep-name shared --json
```

`subdir`是仓库内项目／源码目录，`target`是最终行为包内的位置，不是缓存路径或本机绝对路径。Addon导出不填target。框架快捷选项script-dir/source与普通Git的kind/subdir/target属于不同入口，不混用参数。

同一来源重复add默认保留既有提交和布局。首次不指定ref会解析当时HEAD并锁成完整SHA；它不表示每次sync追踪HEAD。

### 克隆后恢复与验证

```text
mcpy --project "<项目>" --non-interactive sync --json
mcpy --project "<项目>" --non-interactive package --json
```

恢复不需要重新选择框架版本，也不需要重复添加预设。`sync --install`还会在工具环境可编辑安装项目；不要仅为恢复游戏代码而添加这个选项。引擎与工具环境的Python依赖仍需分别满足。

检查返回 `ok` 和退出码；Git项目add结果中 `dependency/rev/kind/target` 描述实际注册结果，快捷入口还返回 `new_script/warnings`；兼容旧代码库时按其实际返回字段处理。package的 `artifact` 是最终ZIP。`synced=true`仅证明依赖准备完成，入口接入和游戏加载仍需验证。

## 来源、更新与移除

支持HTTPS和file://本地Git仓库。QuMod快捷入口可增加 `--source gitee`；已有Git声明切换来源会保留其固定提交，不自动回退到第三方镜像。用户明确选择某个版本／Git链接时，不用预设推荐版本替换其选择。

预设返回的版本来自已验证源码，不保证存在同名官方Release；以CLI返回和锁定的rev为准，不在Skill中另维护“最新版本”。

更新或回退示例：

```text
mcpy --project "<项目>" --non-interactive add --git "<原URL>" --dep-name shared --ref "<目标提交或标签>" --json
mcpy --project "<项目>" --non-interactive package --json
mcpy --project "<项目>" --non-interactive remove --git shared --json
```

升级按既有别名更新，不通过改名添加第二份占用同一目标的库。更换为fork等不同来源时，明确补充需要保留的subdir/kind/target。移除只删声明，不删缓存或入口；随后检查业务导入和重新组装。

旧 `code_libraries` 使用 `remove --library <name>`，不是remove --git。旧格式可继续sync，QuMod快捷添加识别已有兼容声明时不制造重复项；需要迁移格式或改变旧来源时明确处理原声明，不删除业务文件来消除冲突。

## 标准项目描述与边界

消费者持有 `[[tool.mcpywrap.git_dependencies]]`：必需 `name/git/rev`，可选 `subdir/kind/target`；持久化的rev是完整提交。一般让add生成它，不手工猜锁文件。

发布者可以在远端pyproject.toml声明：

```toml
[tool.mcpywrap.export]
kind = "code"
path = "src"
target = "MyMod/SharedLib"
```

export.path相对该项目描述。没有export时工具可识别符合既有目录规则的Addon；无法识别时需要明确布局，不能把任意仓库根目录或安装成功的Python包直接当作游戏依赖。

远端可声明同样的Git子依赖。仓库内local_dependencies相对声明项目解析，必须留在该Git快照内；外部仓库用Git声明。工具解析传递关系、检测循环和目标冲突，但不推断未声明的import，不自动安装Git子模块、不执行上游构建脚本、不求解版本范围。Python project.dependencies仍表示工具环境依赖。

## 缓存、提交与异常处理

用户级不可变Git快照共享下载；项目 `.mcpy/` 保存独立注册节点与组装结果，游戏不直接加载共享源码。`MCPY_CACHE_DIR`用于本机／CI缓存策略，不写进可移植的项目依赖声明。

提交配置、`mcpy-git.lock.json`、生成的入口和业务代码、.gitignore；忽略.mcpy、.runtime、build和dist。旧格式则保留其 `mcpy-code-libraries.lock.json`。不要提交QuMod源码，不要修改共享缓存来开发依赖。

| 情况 | 处理 |
|---|---|
| CLI没有--git或--qumod | 检查bootstrap能力，使用明确来源升级CLI；Skill更新不会更新CLI |
| 新克隆缺少缓存 | 执行sync，保留现有锁定提交 |
| 布局无法识别 | 查上游export/目录，再传明确subdir、kind、target；不猜安装位置 |
| 目标已有手工框架或另一依赖 | 核对归属并制定明确迁移；不直接覆盖或删业务目录 |
| 源码摘要不符 | 定位具体缓存条目，保留锁的预期内容；不删锁或清空全部缓存来掩盖差异 |
| 获取来源失败 | 保留失败信息及现有声明，不静默换镜像、更新版本或转为pip安装 |
| 构建成功但游戏导入失败 | 检查产物路径、入口、端侧与游戏日志；不是工具Python缺包的充分证据 |

QuMod的QMain绑定类须暴露在modMain中，入口模板已包含它；tick回调允许无参数。其系统与RPC命名依赖脚本根，因此独立Mod需要各自的框架作用域。不要把共享下载缓存误解成共享运行时实例。

最后分别报告依赖恢复、产物构建、实际游戏加载的结果；模拟测试和进程启动不能冒充玩法、多人与框架生命周期验收。
