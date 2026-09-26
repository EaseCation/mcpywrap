# 本地目录依赖验收记录

验收日期：2026-09-26。系统：Windows。Python：3.12.14。真实游戏引擎：MCS `3.10.0.420447`。

## 实现结果

- 主项目用 `tool.mcpywrap.local_dependencies` 声明本地 Addon，目标无需初始化、安装或具备配置文件。
- CLI、初始化向导和 GUI 共用声明及依赖图服务，支持添加、移除、目录预检、缺失 Python 包警告和启动前完整校验。
- Python requirement 支持包名规范化、版本约束及环境标记；普通 Python 包不作为 Addon 加载。
- 本地路径按声明项目解析，以真实路径去重并检查循环。独立内部标识避免同名项目的链接碰撞。
- 构建与文件监控共用合并逻辑：稳定依赖优先遍历，主项目最后；文件删除后恢复低优先级来源。
- 运行、编辑器及监控接入同一包集合；构建输出布局在清空前检查。GUI 每次启动重新读取配置。
- 全局链接不再清空其他项目链接；Windows 无符号链接权限时使用目录 junction。游戏启动使用参数列表、引擎工作目录及本次启动的进程句柄。

## 自动化验证

`python -m unittest discover -s tests -v`：**32 项全部通过，无跳过**。

覆盖真实临时 Addon、相对／绝对／中文／空格路径、Windows 大小写和 junction、同名目录、共享子依赖、完整循环链、无配置目录、仅资源包、不同 manifest 文件名、缺失包、版本限制、已删除的 editable 来源目录、普通 Python 库、CLI 非交互和向导、初始化向导、安装失败回滚、失效引用移除、输出保护、地图构建、增量覆盖回退、运行前重验、编辑器包路径、GUI 浏览取消与绝对路径、失效状态、后台安装成功／失败及忙碌状态。

同时通过 `compileall` 和 `git diff --check`。本机已安装的 `mcpy add --help` 已展示新 `--path` 入口（工具采用 editable 安装）。

## 多项目真实集成测试

测试目录：`D:/coding/mcpywrap/test/acceptance-final`，属于 Git 忽略的本机验收产物。

通过独立 uv 环境安装当前工具及一个实际 editable Python Addon，执行真实 CLI 和 pip。项目组合：

```text
local-main
├── a/shared ──┐
├── b/shared ──┼── 中文 common（无 pyproject.toml）
├── resources only（只有资源包，无 pyproject.toml）
└── 中文 common（再直接引用，与间接引用去重）

mixed-main
├── Python requirement: mcpy-test-package>=1.0
│   └── python-package ── 中文 common
└── b/shared ── 中文 common
```

已验证：

1. 真实 CLI 添加相对路径和绝对路径、重复添加去重、同名目录无覆盖，构建包含全部脚本。
2. 实际安装的 Python Addon 与本地目录参与同一图，共享子依赖只出现一次。
3. 真实 watchdog 观察新增目录／文件、重命名、删除。删除主项目的覆盖文件后恢复 `b/shared` 内容，增量文件哈希与完整重建完全相同。
4. 循环添加失败且配置不变；依赖无效时构建失败且已有输出不变；不存在的目录声明仍能移除。
5. `中文 common` 在添加、构建、运行前后的文件哈希完全一致，没有配置或安装元数据写入。
6. 额外以 D 盘主项目引用 C 盘临时 Addon，自动存储绝对路径，实际 CLI 构建成功，源文件未变。测试完先移除声明，再回收该临时源目录。

跨盘补测首次因测试子进程使用 GBK 输出表情字符而失败；固定验收子进程 `PYTHONIOENCODING=utf-8` 后重跑通过。该次失败发生在构建成功后的提示输出阶段。

## 真实游戏加载验证

调用产品的实际运行入口生成 cppconfig、创建系统目录链接、启动本机 MCS 引擎；仅将独立日志窗口替换为预先监听的 TCP 文件收集器。没有替换游戏进程或包链接操作。

每个测试 Mod 使用独立脚本包和 `Mod.Binding` 名称，在 `InitServer`、`InitClient` 输出唯一标记。除了日志，还对比游戏实际生成的 `netease_world_behavior_packs.json` 和 `netease_world_resource_packs.json` 中的 UUID。

| 场景 | 行为包 / 资源包 | 服务端标记 | 客户端标记 | 游戏生成的 UUID 集合 |
|---|---:|---:|---:|---|
| 纯本地依赖，独立包运行 | 4 / 5 | 4/4 | 4/4 | 完全匹配 |
| 纯本地依赖，合并产物独立运行 | 1 / 1 | 4/4 | 4/4 | 完全匹配 |
| Python + 本地混合，独立包运行 | 4 / 4 | 4/4 | 4/4 | 完全匹配 |
| 混合依赖，合并产物独立运行 | 1 / 1 | 4/4 | 4/4 | 完全匹配 |

**四组均通过，共 32 个加载标记。** 合并产物测试仅在输出目录添加最小主项目配置，不声明任何源依赖，确认脚本已经被组装到产物内。

测试游戏进程已按各自 PID 结束，本次新建的全局链接已移除；测试项目、日志和独立存档保留供复查。未停止用户的 MCStudio。Safaia 辅助服务沿用产品启动逻辑。

引擎日志含自身的通用启动报错（例如 `get_world_record: None`），但四组测试的全部初始化回调均已执行。此次证明包注册和 Mod 初始化加载成功，不声称验证了所有纹理外观、玩法或第三方网络服连接。MCS 3.10 网络服适配仍在本次范围之外。

## 证据与复现

- 可复现脚本：[tests/manual_integration.py](../tests/manual_integration.py)
- 自动化用例：[tests/test_local_dependencies.py](../tests/test_local_dependencies.py)
- 本机完整结果：[report.json](../test/acceptance-final/report.json)
- 跨盘结果：[cross-drive-report.json](../test/acceptance-final/cross-drive-report.json)
- 最终自动化输出：[unit-tests.log](../test/acceptance-final/unit-tests.log)
- [纯本地日志](../test/acceptance-final/local-main-game.log)、[纯本地产物日志](../test/acceptance-final/local-main-assembled-game.log)
- [混合依赖日志](../test/acceptance-final/mixed-main-game.log)、[混合产物日志](../test/acceptance-final/mixed-main-assembled-game.log)
- [GUI 路径预览](../test/acceptance-final/gui-local-preview.png)

GUI 截图由 Qt 离屏渲染生成，显式加载本机微软雅黑字体以解决离屏平台缺少字体的问题。截图检查后将路径预览改成可滚动的只读文本框，避免长路径遮住保存形式和包结构信息。

复现命令见 README“开发验证”；使用新的、尚不存在的 `--workspace`，测试前关闭正在运行的 Minecraft。以上 `test/` 证据是本机保留文件，不随源码分发。
