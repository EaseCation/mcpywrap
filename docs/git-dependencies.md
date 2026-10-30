# Git 项目依赖与共享缓存

远程项目是通用依赖来源，QuMod 等框架只是预设。核心不识别框架名称：获取层负责Git源码快照，解析层负责导出描述和依赖图，注册层生成项目独立的组装节点，已有构建器消费这些节点。

## 添加和恢复

```powershell
# 自动识别已有Addon，或读取仓库的导出描述
mcpy add --git https://example.com/team/shared-addon.git --ref v1.2.0

# 没有项目描述的普通源码目录：显式补充布局
mcpy add --git https://example.com/team/shared-code.git --kind code --subdir src --target MyMod/SharedLib

# 固定某个提交、别名、monorepo项目目录
mcpy add --git https://example.com/team/modules.git --ref <完整SHA> --dep-name combat --subdir projects/combat

# 克隆已配置项目后恢复依赖；有完整共享快照时不需要重新下载
mcpy sync
mcpy remove --git combat
```

支持HTTPS与file://本地Git仓库；访问权限交给Git凭据机制。首次省略ref会读取当时HEAD并保存完整SHA，重复添加同名来源默认保留版本。显式ref用于更新或回退，不自动选择最新版本，不提供版本范围求解。

图形界面 `mcpy ui` 的“Git依赖”表单使用同一服务。“一键添加 QuMod”等快捷按钮只填入标准Git来源与布局，并可为新脚本目录生成入口；添加后仍是普通Git依赖，不单独分类为框架。

## 消费者与发布者的标准描述

消费者的pyproject.toml：

```toml
[[tool.mcpywrap.git_dependencies]]
name = "shared"
git = "https://example.com/team/shared.git"
rev = "0123456789abcdef0123456789abcdef01234567"
subdir = "."  # 可选：项目描述所在目录
kind = "auto" # 可选：auto / addon / code
# target = "MyMod/SharedLib" # code安装位置，可覆盖上游export.target
```

远端项目可在自己的pyproject.toml声明导出：

```toml
[tool.mcpywrap.export]
kind = "code"
path = "src"
target = "MyMod/SharedLib"
```

`export.path`相对项目描述所在目录；`target`相对最终行为包。已有有效Addon可省略export，由manifest及现有Addon目录规则识别；Addon不需要target。没有描述且无法识别时明确报错，不猜测任意Git项目的安装结构，不运行setup.py、构建脚本或EXE。

子项目使用相同git_dependencies声明，提交须固定。仓库内部的local_dependencies相对声明项目解析，必须位于同一Git快照内，支持monorepo；外部仓库必须显式用Git依赖。工具递归解析、检测循环、去重共同节点，并拒绝代码安装位置与手写内容或其他依赖重叠。

Python的project.dependencies继续表示工具Python依赖，不变成游戏代码安装指令。远端项目中的旧code_libraries仍可使用；未声明的import、Git子模块和任意构建系统不会被自动推断为依赖。

## 混合存储模型

| 层 | 位置 | 内容 |
|---|---|---|
| 共享源码 | Windows `%LOCALAPPDATA%/mcpywrap`；macOS `~/Library/Caches/mcpywrap`；Linux `$XDG_CACHE_HOME/mcpywrap`或`~/.cache/mcpywrap` | 按来源和完整提交保存不可变快照及摘要 |
| 项目锁 | `mcpy-git.lock.json` | 直接声明、解析节点、子依赖关系、内容摘要；不记录本机缓存绝对路径 |
| 项目注册 | `.mcpy/git-projects/` | 从源码复制并标准化后的Addon节点、布局与项目内相对依赖关系 |
| 游戏产物 | `.mcpy/runtime/`、配置的build目录及dist | 独立组装结果；不指向共享源码 |

`MCPY_CACHE_DIR`覆盖共享缓存根目录，CI可以指向临时目录，需要项目内缓存时可指向项目自己的`.mcpy/cache`。这是本机获取策略，不改变依赖声明、锁文件或安装作用域。

同一提交只需下载一次，但每个项目独立选择版本，每个Mod独立选择框架安装位置。产物使用复制，修改产物不会反向写共享缓存。Git源码通过临时目录校验后原子发布，同来源并发下载使用跨进程锁，进程退出后由操作系统释放锁。Windows内部缓存支持长路径，不要求更改系统配置。

项目注册节点另含注册格式版本；工具调整注册布局时，显式sync重建派生节点，源码提交仍保持锁定。各Git依赖的许可/NOTICE分别保存在包内 `mcpy_licenses/<节点ID>/`，避免多依赖组装时互相覆盖。

只有add/sync获取远程内容，build/package/run不隐式联网。共享缓存校验不通过时报错，不覆盖损坏内容，也不删除锁文件来“修复”。本版不自动垃圾回收缓存；移除声明保留源码缓存、手写入口和已有产物，下一次组装更新产物。

提交配置、锁文件、业务源码及.gitignore，忽略.mcpy、.runtime、build和dist。旧code_libraries与mcpy-code-libraries.lock.json兼容，获取层同样复用用户级源码缓存，不要求已有项目迁移。


## Windows 与 macOS 共用锁文件

两端提交并使用同一份 `mcpy-git.lock.json`，无需维护平台分支。锁定的是 Git 提交、源码和依赖关系；本机安装目录位于 `.mcpy/`，不提交到 Git。当前依赖都是游戏源码，没有需要分别锁定的 Windows/macOS 原生包。

v2 锁使用相同的大小写敏感路径排序；源码由 Git archive 提取，禁用宿主 Git 的换行、编码、ident 和 filter 转换及全局 attributes，保留提交中的文件字节（包括二进制和原本的 CRLF）。工具生成的文件统一使用 LF。新机器或克隆项目后运行一次 `mcpy sync`，随后正常 `mcpy run`。

`mcpy sync` 依据声明中固定的完整 Git 提交重新计算源码和安装内容摘要，直接写回锁文件；不更新依赖版本、不创建备份或执行专门的锁迁移。旧 v1/v2 锁都可通过一次 sync 刷新。新快照使用独立的 `git-archive-v2` 缓存，首次同步会重新获取固定提交，之后可离线复用；旧缓存不参与新摘要计算。已安装副本与旧锁一致时可重建，手动改动或缓存损坏仍会报错。`build/package/run` 继续严格验证锁文件，不隐式重算。

终端只显示同步进度、结果和必要操作；`mcpy sync --json` 返回结构化结果。`--migrate-windows-lock` 和 JSON 中始终为空的 `git_lock_migrations` 仅保留旧脚本兼容。团队各设备应使用包含此修复的版本，并提交 sync 更新后的锁文件。

测试入口见[测试说明](../tests/README.md)。

## 不随构建打包：unbundled

通用 Git Addon/code 支持布尔标记 `unbundled`，默认 false。它属于依赖引用，不参与源码或安装节点身份计算。true 时仅随运行图加载；发布图排除该引用，但仍保留其他普通路径需要的共享节点。

含新标记语义的锁使用 v3；旧项目继续使用 v2。默认 sync 恢复完整运行图，部分恢复只安装发布节点并保留其余锁记录；build/package 只校验有效节点。上游项目自身的 unbundled 引用不自动获取。旧 code_libraries 和生成业务入口的框架快捷依赖继续随发布。

CLI、配置和预览用法统一见 [Skill 的 unbundled 指引](../skills/mcpywrap/references/project-dependencies.md#不随构建打包unbundled)。
