# 统一输入实现

Agent 的推荐入口是 `runtime input observe → run → status/cancel`；公开协议与示例见 [统一输入](../skills/mcpywrap/references/runtime-input.md)。单键快捷命令生成同一JSON计划，默认后端game，设备测试显式选择windows-sendinput。

`input_plan.py` 保存动作注册表、集中键名映射、字段验证、规范化与限制。能力查询、CLI帮助与schema均从注册表生成；不在客户端、远程和游戏中维护不同参数表。输入源码按原有32KiB上限分段暂存，全部确认后才安装。

`input_executor.py` 是两后端共用的有界状态机：先编译绝对计划时刻，完成型动作等待自身结束，瞬时边沿保留计划持有集合，wait保留实际等待。调度器不改变旧sequence的计划语义，也不把动态目标或完成依赖平铺成静态边沿。

游戏适配复用既有玩家/UI客户端路径，增加新旧入口互斥。UI单节点操作保持快照校验，修饰键在动作前按下、动作结束后释放；菜单键盘不再受player的HUD限制，界面切换仍停止后续计划。玩家语义输入与原始设备输入路径分别记录。

Windows适配在会话worker中保留状态与幂等历史，单个调度线程推进操作；远程input端点只传参数。统一游戏控制层预留防止新旧游戏写请求插入设备计划；已持有的系统键或修饰键拒绝接管。未知释放保持busy，支持stop重试，不扩大为多请求共享输入。

原生 Mac 单调时钟及启动器结构规则位于 `native/runtime_input`。运行包通过 `launcher.steady_clock` 提供计时能力；缺少该接口时返回 `missing_monotonic_clock`，需升级配套资源并新建实例。原始 pointer/text 缺少能力时保持不支持。

兼容入口保留原有修饰键排序、时间原点和输入后端，仅从默认发现入口隐藏。测试入口见[测试说明](../tests/README.md)。
