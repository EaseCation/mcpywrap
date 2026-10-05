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

## 使用

普通 `mcpy run --new` 的 GUI 路径先展示紧凑确认框；世界设置默认折叠，直接
“创建并运行”使用默认值。展开后可调整 cppconfig 的全部已建模世界字段。
不支持的选项显示原因。菜单支持从 cppconfig 或选中实例的创建配置新建，复制
配置不复制存档、不复用 ID，也不导入身份凭据或旧资源路径。

纯命令创建，无需先创建或编辑配置文件：

```sh
mcpy --local --project /path/to/addon --non-interactive run --new --no-gui --detach \
  --world-name survival-test --world-type infinite --seed 67890 \
  --game-type survival --difficulty hard --no-keep-inventory --show-coordinates --json
```

完整参数见 `mcpy run --help` 和 [AI 使用说明](../skills/mcpywrap/references/instance-world-settings.md)。
优先级为本次命令参数 > `--cppconfig` 导入的世界字段 > 工具默认值。
创建参数只允许与 `--new` 同用；重开指定实例不接受这些参数。

`run --list --json` 返回实例配置路径。磁盘 cppconfig 是创建配方，不是当前运行
状态；游戏内更改后不据此展示“当前难度”。当前设置通过游戏接口读取，保存后
以存档为准。不要在运行时手改 cppconfig 或 level.dat。

## 兼容与验证

新 macOS 运行包声明 `cppconfig_protocol=1`。已有实例保持固定的运行包，旧包仍
可按原协议启动原实例；显式世界选项要求新运行包并新建实例，不会假装旧包已
应用参数。新协议打开旧目录时可以读取存档设置建立 cppconfig，不移动存档。
Windows Map 项目首次复制原存档，重开不再重复覆盖已有 level.dat/LevelDB。

macOS 当前不支持启用 cppconfig 中的 `experimental_holiday`、`experimental_biomes`
和 `fancy_bubbles`；显式启用会报错。未验证字段不静默忽略。CLI 与 GUI 共享限制。
编辑已有世界的设置使用游戏本身的界面/API；本轮创建参数不会变成启动时覆盖存档的开关。

自动测试覆盖配置持久性、只刷新派生路径、导入隔离、CLI 覆盖优先级、GUI 确认与
取消，以及两端后端调用。macOS 实机还需核对生成器/种子/模式/难度/规则、保存后
重开和双实例隔离；Windows 实机回归需在 Windows 上执行。
