# 测试实例与 cppconfig

世界设置属于测试实例，不写入项目 pyproject.toml。两个本地后端共享 MC Studio
cppconfig 的 `world_info` 字段；Qt 与 CLI 先写入实例配置，再启动对应后端。

| 职责 | 共用行为 | Windows | macOS |
|---|---|---|---|
| 创建参数 | `world_info` 的生成器、种子、模式、难度、权限、规则 | `.runtime/<id>.cppconfig` | `.runtime/macos/instances/<id>/world.cppconfig` |
| 资源组装 | 沿用项目依赖与 pack 构建 | 刷新本机 pack 链接 | cppconfig 保存 pack 路径，适配器安装后转换为 Android 包标识 |
| 引擎与进程 | 不把安装、日志、控制通道混入世界选项 | 原有引擎发现及 session | 原有 instance.json 安装绑定及 session |
| 打开已有世界 | 存档状态优先，创建参数不反复覆盖 | 只读 level.dat，生成本次 session 的有效 cppconfig | 不再次调用 create_world/set_world_info |
| 默认值 | 无限、创造、普通难度、开启作弊，种子留空由游戏生成 | 沿用原有默认值 | 新协议与 Windows 一致；旧实例不改存档 |

cppconfig 是网易开发端已有格式，不是 Bedrock 全平台统一标准。Android 的官方
`studio_message_handler.startGame` 本身使用同名字段转调 world API：
`world_type` 对应 GeneratorType（1=无限，2=平坦），其余字段经适配器转换到
`basic_info`、`option_info`、`cheat_info`。没有新增二进制入口。

## 用户入口

世界参数、模板优先级与实例操作统一维护在 [Skill 世界设置](../skills/mcpywrap/references/instance-world-settings.md)。本页保留 cppconfig 适配与偏好持久化契约，不复制 CLI 操作教程。

## 兼容性

新 macOS 运行包声明 `cppconfig_protocol=1`。已有实例保持固定的运行包，旧包仍
可按原协议启动原实例；显式世界选项要求新运行包并新建实例，不会假装旧包已
应用参数。新协议打开旧目录时可以读取存档设置建立 cppconfig，不移动存档。
Windows Map 项目首次复制原存档，重开不再重复覆盖已有 level.dat/LevelDB。

macOS 当前不支持启用 cppconfig 中的 `experimental_holiday`、`experimental_biomes`
和 `fancy_bubbles`；显式启用会报错。未验证字段不静默忽略。CLI 与 GUI 共享限制。
编辑已有世界的设置使用游戏本身的界面/API；创建参数不会变成启动时覆盖存档的开关。

测试入口见[测试说明](../tests/README.md)。

## 用户偏好与世界配置的区别

FPS 显示、启动器 VSync、游戏画质、GUI 缩放、音量、键位等属于用户偏好，
不属于 cppconfig 或单个世界。Windows 沿用游戏的用户级配置目录；macOS 的
mcpy worker 将原生配置中的偏好字段保存在
`~/Library/Application Support/mcpy/preferences/macos/`（设置 MCPY_ENGINE_HOME 时跟随该目录）。

继续使用 `mcpelauncher-client-settings.txt` 和 `options.txt` 原生格式。启动时带入
共享值，运行期间同步游戏已经写入的改动，正常退出后再刷新一次。只合并本会话
实际改变的字段，避免同时运行的旧实例用整份旧文件覆盖新偏好。运行中的另一个
实例不会被强行实时改变；下次启动读取最新共享值。

首次启用时优先导入所选实例的已有偏好；没有时从当前项目最近保存的实例导入。
已有共享偏好优先。账号、身份、调试凭据、世界难度及存档等不共享。不同项目和
同一资源根目录下的不同运行包共用偏好，删除实例不会删除这些用户偏好。
