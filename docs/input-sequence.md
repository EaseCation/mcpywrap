# 统一编排与 Windows 输入时序

公开入口与参数维护在 [Skill 编排说明](../skills/mcpywrap/references/input-sequence.md)。`input-sequence` 扩展 Windows 桌面输入；原有 `key`、`mouse` 和游戏内 `runtime player sequence` 仍可使用。

## 实现边界

- `core/mcpywrap_core/timeline.py` 是唯一的时间计划生成器：省略 `at_ms` 时按上一步计划结束和 `delay_ms` 生成，显式时间也进入相同计划。它同时被工具 Python 导入和注入游戏 Python 2，不依赖 Win32 或游戏 SDK。
- `mcstudio/window.py` 的 `InputSender` 是唯一的 Windows `SendInput` 调用与输入释放实现。旧 key/mouse 和新编排共用它，旧命令的保持时长、修饰键提前量和返回格式不变。
- `mcstudio/input_sequence.py` 只负责 Windows 事件计划验证、等待、目标检查和结果汇总。相同时间的相邻按钮/键盘事件批量提交，移动与滚轮保留校验边界。开始前完整核对进程身份，执行时检查已持有进程句柄是否存活、焦点、几何和鼠标目标。
- `mcstudio/runtime_player_payload.py` 保留游戏内动作执行器：游戏 tick、快照、物品与目标断言不能与 Windows 调度混用。旧步骤先编译为时间表，移除人为的 100 ms 步骤间隔，实际延迟记录在步骤结果中。

Windows 使用绝对截止时间、较长空隙的短 sleep 和最后不超过约 2 ms 的忙等，不修改系统时钟粒度或进程优先级。OS 调度、API 调用及游戏处理均可能带来抖动，不承诺硬实时。记录的是 SendInput 调用边界，同一批次不伪造逐事件内核时间。

本机和远程桌面输入共用 Windows 会话内的命名互斥，避免 key/mouse 与时间表交错。远程仍使用原桌面操作锁与协议版本 1，只增加 `input-sequence` 能力和接口；旧客户端不受影响，新客户端遇到旧服务会在发送前报能力不足。文件在调用端读取，不把调用端路径交给远端。

测试入口见[测试说明](../tests/README.md)。
