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

## 验证范围

自动化测试使用与任何框架无关的本地Git仓库，覆盖Addon自动识别、代码导出、Git子依赖与仓库内引用、循环/越界、项目隔离、离线恢复、并发下载、更新/回退/移除、内容篡改和深层Windows路径。官方QuMod GitHub与Gitee固定提交的完整源码摘要一致，均通过创建框架、打包和干净克隆sync。

这保证依赖获取与组装契约，不自动保证任意第三方代码兼容游戏。Git子模块、跨仓库可变本地路径、版本范围和上游构建钩子不在本版支持范围。

2026-09-27 验证记录：全量246项通过；随后Git依赖UI统一命名、快捷取消和自动导出返回值的针对性回归通过。并发首次获取重复5轮通过，Skill校验及真实CLI能力检测通过。Windows原生Qt窗口已检查，离屏测试不用于证明文字渲染。官方两来源固定提交完整源码摘要均为 `480e7e0bd9b99fc6b9e0f61a96fb68ea8c64752e25d19d8ab72edfbb885d4ebf`。
