# 本地测试实例的世界设置

Windows/macOS 使用同一套 `run` 参数。设置归属实例，不写 pyproject.toml；不需要
先创建世界再编辑文件。先检查本机 `run --help`，新 macOS 运行包还须支持
`cppconfig_protocol=1`（`mcpy --local engine doctor --json` 返回该字段）。旧实例仍固定旧运行包，更新 CLI 不会升级它。

```sh
mcpy --local --project /path/to/addon --non-interactive run --new --no-gui --detach \
  --world-name flat-test --world-type flat --game-type creative --difficulty peaceful \
  --seed 12345 --show-coordinates --no-mob-spawn --random-tick-speed 4 --json

mcpy --local --project /path/to/addon --non-interactive run --new --no-gui --detach \
  --world-name survival-test --world-type infinite --game-type survival --difficulty hard \
  --seed 67890 --no-cheats --no-keep-inventory --bonus-items --start-with-map --json
```

省略参数采用工具默认值：无限、创造、普通难度、开启作弊、空种子由游戏生成。
所有创建选项要求 `--new`。后续 `run <实例ID前缀>` 打开原世界，不重复传创建参数。
`run --list --json` 查找实例 ID 和配置路径；session ID 与实例 ID 不同。

| 创建参数 | 值 |
|---|---|
| `--world-name` / `--seed` | 字符串；种子应作为字符串传递，`--seed 0` 是有效种子 |
| `--world-type` | `infinite` / `flat` |
| `--game-type` | `survival` / `creative` / `adventure` |
| `--difficulty` | `peaceful` / `easy` / `normal` / `hard` |
| `--permission-level` | `visitor` / `member` / `operator` |
| `--cheats` / `--no-cheats` | 开关作弊 |
| `--start-with-map` / `--no-start-with-map` | 初始地图 |
| `--bonus-items` / `--no-bonus-items` | 奖励箱 |
| `--random-tick-speed` | 非负 32 位整数 |

以下游戏规则均有 `--名称` / `--no-名称` 两个开关：

`pvp`、`show-coordinates`、`always-day`、`daylight-cycle`、`fire-spreads`、
`tnt-explodes`、`keep-inventory`、`mob-spawn`、`natural-regeneration`、`mob-loot`、
`mob-griefing`、`tile-drops`、`entities-drop-loot`、`weather-cycle`、`command-blocks-enabled`、
`experimental-holiday`、`experimental-biomes`、`fancy-bubbles`。

macOS 暂不支持启用最后三项，显式启用会失败；不要绕过限制或把默认 false 当成已验证支持。

可选 `--cppconfig /path/to/template.cppconfig` 导入已有 `world_info`，并通过上述参数
覆盖个别值。优先级：显式命令参数 > 模板字段 > 默认值。只导入世界设置，不复用
世界 ID、引擎版本、身份凭据或旧 pack 路径。也可用旧实例 cppconfig 作为新世界模板。

返回 running 只证明进程已启动；用同一 session 的 status/logs/runtime py 等待世界
就绪，读取实际设置确认效果。测试结束 stop 自己创建的 session。cppconfig 保存的是
创建配方，游戏内修改后的当前设置保存在存档，不因重开而重新应用创建配方。
禁止从 cppconfig 的初始 difficulty 推断当前世界难度。

GUI 是供人工使用的同一入口：新建确认框默认收起世界设置，直接确认采用默认值，
展开后可修改全部已建模选项；Agent 使用上面的纯命令入口，不操作确认框。
