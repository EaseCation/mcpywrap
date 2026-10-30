# 依赖的 unbundled 打包标记

状态：已实现。默认 `unbundled = false`。日期：2026-10-30。

## 契约

`unbundled` 是依赖引用上的布尔值。false 表示随 build/package 发布；true 表示 dev/run 照常加载，但 build/package 排除。旧字符串形式的本地依赖、未填标记的 Git 依赖都默认 false。

```toml
[tool.mcpywrap]
local_dependencies = ["../shared", { path = "../test-helper", unbundled = true }]

[[tool.mcpywrap.git_dependencies]]
name = "test-helper"
git = "https://example.com/team/test-helper.git"
rev = "0123456789abcdef0123456789abcdef01234567"
unbundled = true
```

不引入 main/dev 依赖类别，避免与 dev 命令混淆；也不使用 Java 中通常表示合并依赖的 Shadow/Shade 命名。该标记只控制是否随产物发布，不表示 optional、外部宿主提供、源码替换或独立 Addon 加载。

## 入口与反馈

- `add --path/--git --unbundled` 设置 true；`--bundled` 设置 false。新依赖省略时默认 false；更新已有依赖省略时保留原值。
- `dev`、本地 `run`、本地双客户端组和 Windows edit 选择运行图，包含根项目的 unbundled 引用。
- `build`、`package` 选择发布图，组装前排除 unbundled 引用。package 从源码独立组装。
- `deps --json` 只读预览运行图；`deps --bundled-only --json` 预览发布图。
- 默认 sync 准备运行图；`sync --bundled-only` 恢复已锁定的发布图，保留未安装节点的锁记录。
- 网络连接和远程运行保持原有端侧限制，不因这个标记自动向服务器安装依赖。

UI 使用默认不勾选的“不随构建打包（unbundled）”复选框，列表显示是否随构建打包，允许修改已有设置与查看发布引用链。Python 工具包不显示此选项。

add JSON 返回 `unbundled`、`previous_unbundled`、`included_in_release`。有效图包含 `purpose`（runtime/release）、`includes_unbundled`、节点 `unbundled`、`via` 和 `excluded`。节点布尔值由当前根项目的有效引用关系决定。

## 传递与共享节点

只有当前根项目的 unbundled 引用在运行图中启用。进入依赖项目后只跟随普通打包引用，不加载该依赖自己的 unbundled 辅助工具。

```text
P --false--> A --false--> C
P --true---> B --false--> C
                 +--false--> D
A --true---> A-helper
B --true---> B-helper
```

运行图为 A、B、C、D；发布图为 A、C。A-helper、B-helper 不自动启用。B 所需的 D 必须加载，“unbundled 不向消费者传递”不能被解释成 B 的正常子依赖也被排除。

C 即使经不打包路径可达，也因为存在普通打包路径而进入发布。去重不能掩盖这条路径；预览必须解释它为什么仍会发布。相同源码但安装 target 不同，仍可成为不同安装节点。

## 鲁棒性

1. **先选择图。** 发布不读取未选中依赖的内容、校验其本地副本或发现其准备入口。未安装的 unbundled 路径和私有副本不阻塞发布；配置语法和锁拓扑仍需校验。
2. **严格布尔值。** 拒绝 `"true"`、1、空值、错误字段与旧 scope 语法，不把输入错误当作 false。来源类型与打包标记独立；宿主 Python 包不使用此字段。
3. **统一用途上下文。** 解析结果携带根项目与 runtime/release 用途，构建器拒绝复用错误项目或错误用途的 manager。准备、组装、部署和监控使用同一有效图。
4. **Git 注册保留语义。** 同步时过滤上游自身 unbundled 引用；源码和安装节点身份不包含根引用上的标记。含新语义的锁用 v3，普通旧项目仍为 v2。
5. **一份锁，按图恢复。** 运行图与发布图共享锁；部分恢复不删除、伪造或要求安装未选中的 unbundled 节点。build/package/run 不隐式联网、不更新版本。
6. **防止残留和竞争。** build 完整替换输出，清理 dev 留下的不发布内容；dev 与 build 不能同时写同一目标。watcher 的增量和完整重建都保持运行图。package 独立组装。
7. **保护正式模块。** unbundled 独占内容不能覆盖随发布的 Python 模块，已有代码 target 冲突规则继续生效；标记不改变现有资源合并和包身份规则。
8. **限制有副作用的准备。** unbundled 独占依赖暂不支持 consumer_prepare；否则生成到主源码包的文件会绕过图筛选进入发布。未来支持需先提供输出归属、隔离和安全清理。根 hooks 的副作用仍需单独验收。
9. **固定会话选择。** 热更沿用会话运行图，修改依赖或打包标记仍按生命周期重启。去掉依赖不会清除其写入世界的实体、方块和业务数据。
10. **检查最终产物。** Python 动态导入无法全部静态验证。正式代码不能依赖被排除的模块，运行组装成功不代表 ZIP 已独立验收。
