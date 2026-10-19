# 为依赖导出消费者准备入口

用于框架作者交付“读取最终消费项目素材并生成资源”的能力。添加依赖、工具环境和执行时机见[消费者使用](consumer-prepare.md)；为框架仓库自身构建发布物仍使用[根项目脚本](project-scripts.md)。

## 声明与交付

在依赖原始 pyproject.toml 声明一个可直接执行的 Python 文件入口：

```toml
[tool.mcpywrap.consumer_prepare]
format = 1
python = "build_tools/prepare.py"
requires_python = ">=3.9"
```

这是最小声明。业务配置需要结构校验或示例时，再增加下面这些可选字段：

```toml
# 添加到上面的 consumer_prepare 表中，不另建第二张同名表
config_key = "tool.catalog"
config_schema = "build_tools/schema.json"
config_example = "build_tools/example.toml"
timeout = 180
transitive = false
```

格式版本为整数 1，未知字段或无效声明会报错。requires_python 使用 PEP 440，描述宿主处理工具所需的 Python，不是游戏内 Python 版本。每个依赖最多一个入口；多个处理步骤在入口内部组织，第三方工具由消费者预先准备，mcpy 不求解或安装这些依赖。

python、schema、example 均相对依赖描述根，真实路径不得越界。消费素材路径则相对 `MCPY_PROJECT_ROOT`。Git 的 subdir 选择描述根，export.path 选择游戏导出内容；即使 build_tools 不在导出子树中，仍从同一锁定源码取得，不能把工具复制进游戏包或从安装目标猜路径。

支持本地 Addon 与 Git addon/code 依赖。入口源码须随依赖交付，不要求消费者先执行依赖自身 hooks 来生成它，也不通过 site-packages 扫描插件。

## 决定作用范围

直接消费者自动接入，无需再启用或绑定阶段。只有间接可达时，默认不执行；如果该能力需要作用于所有上层的最终消费根，作者明确设置 `transitive = true`。每个消费根分别准备，菱形引用和不同安装别名不会重复执行同一来源版本。

框架仓库不是自身的消费者。在框架根运行 build，不能用来证明 consumer_prepare 已接入；使用另一个声明该依赖的 Addon 验证。不要为解决消费者接入问题，把依赖普通 before_build/before_run 改成递归执行。

## 配置、上下文与结果

config_key 是普通点分隔 TOML 表路径。未声明或表不存在时传 `{}`，由 schema 或入口判断是否足够。schema 需要 config_key；使用 JSON Schema Draft 2020-12，仅支持同文件内部引用，不联网、不读取外部 schema、不自动应用 default。跨文件业务语义由入口校验。

多个启用的来源不能占用同一 config_key。TOML 日期、时间、非有限浮点数不能无损传入 JSON，会报告具体字段。config_example 是纯文本说明，不会执行或自动合并进宿主配置。

入口 cwd 为消费根，通过环境变量取得上下文：

| 环境变量 | 含义 |
| --- | --- |
| MCPY_PROJECT_ROOT | 最终消费项目绝对根，素材与生成结果属于它 |
| MCPY_DEPENDENCY_ROOT | 当前依赖原始描述根，只读工具来源 |
| MCPY_CONSUMER_CONFIG | 临时 UTF-8 JSON 文件路径，只含本入口对应的配置表 |
| MCPY_PROVIDER_ID | 日志归属身份，消费者无需手动配置 |
| MCPY_EVENT | before_build、before_package 或 before_run |
| MCPY_OPERATION | build、package 或 run |

读取 JSON 并自行处理；不要依赖 `mcpywrap` 内部 Python API。可通过入口自身位置或 MCPY_DEPENDENCY_ROOT 导入随包模块。工具解释器与游戏解释器独立，生成的游戏代码仍需符合目标 ModSDK/Python 约束。

退出码 0 表示成功，stdout/stderr 保留到统一日志。预期业务错误应说明具体源文件和修法，返回非零。stdin 已关闭；入口不能等待交互、脱离监督成为后台服务或递归调用 mcpy 写操作。timeout 默认 120 秒，可设置大于 0、不超过 86400 的有限秒数。

## 输出归属

入口只维护消费项目中归属于自己的资源和注册项。原始素材保持可编辑，运行库由依赖装配；不要再生成第二份运行库。多文件生成需要作者自行维护所有权账本、原子替换或事务恢复。

不得修改依赖源码/缓存、pyproject、依赖锁、包身份、世界数据库或受管运行目录。将辅助工具放在源码目录，将运行缓存放在消费项目的 `.mcpy` 下；不要在共享依赖根写缓存或生成物。Python 字节码写入默认关闭。

mcpy 统一执行、取消和阻断后续消费，但不提供任意文件访问的沙箱或源码回滚。已开启的外部 watcher 仍可能看到写入中间态；需要多文件一致性时由生成器设计提交过程。

## 从模板开始验证

Skill 自带 [最小框架与消费者](../assets/consumer-prepare/)；完整实现分别见[框架声明](../assets/consumer-prepare/framework/pyproject.toml)和[准备入口](../assets/consumer-prepare/framework/build_tools/prepare.py)。复制整个目录到工作区后使用，模板内的名称、UUID、输入格式和输出路径仅为演示，发布新项目时替换为自己的身份与约定。

以复制后的 game 为项目执行公开 sync、`script list --effective --json` 和 package。检查计划中的来源、环境和 ready，再核对 ZIP：包含生成资源和 CatalogRuntime，不含原始输入、build_tools 或环境。修改 data/items.json 后再构建应更新结果，手工修改生成文件应触发所有权诊断。

生成器模板只维护一个资源文件和摘要账本，二者分别原子替换，不构成跨文件事务。按真实产物复杂度扩展，不把这个示例当作通用资产合并器。

旧项目迁移时，先确认新入口与运行库来自同一依赖，再移除旧框架准备任务、三个 hook 绑定及薄启动器中属于该框架的部分；保留其他项目任务。迁移在构建之外完成，不在 before_run 中改 pyproject。随后重新核对有效计划，避免新旧入口同时执行。
