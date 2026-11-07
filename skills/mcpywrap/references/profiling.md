# 性能分析

卡顿、帧率低、某个操作慢、某段脚本耗时等问题，用游戏内置的 Tracy 测量，不要在业务代码里加时间戳打点。开发版游戏（Windows MC Studio 引擎、macOS 运行包 0.4.7+）启动后自带 Tracy 0.11.1（协议 69），会把**每个 Mod Python 函数**记录为一个区段：名称是函数名，位置是源文件和 def 行号。不改代码就能看到每个函数的调用次数、耗时分布和调用关系，引擎自身的主循环、渲染、tick 等区段也在同一份数据里。

## 前提

- 工具：`mcpy profile install --json` 下载固定版本的分析器、采集和报告工具，已安装时直接返回。网络不稳时已下载部分会保留，重新运行即续传；会依次尝试多个镜像，可用环境变量 `MCPY_TRACY_MIRROR`（逗号分隔的基址）指定镜像，或 `--from <zip>` 导入已下载的工具包（须与内置清单摘要一致）。不要使用系统或 Homebrew 里的其他 Tracy 版本。
- 游戏：本机运行中的会话。macOS 旧实例绑定的运行包低于 0.4.7 时不监听端口，需更新运行包后 `run --new`。游戏只监听 `127.0.0.1`，端口从 8086 起，多实例顺延。
- 远程：暂不支持通过 `--remote` 采集；需要分析 Windows 测试机上的游戏时，在那台机器本机运行 `mcpy profile`。
- 服务端脚本只在本地世界可见（与客户端同进程）；网络会话只能看到客户端。
- Tracy 同时只接受一个连接。用户已经打开实时分析器时采集会返回 `profiler_busy`：告知用户，不要关闭用户的窗口或结束其进程。

## Agent 工作流

1. **固定场景**：`run --no-gui --detach --json` 得到 session，等世界就绪后再用[统一输入](runtime-input.md)或 `runtime py` 进入要分析的场景，让它持续或重复发生。世界加载、首次进入等一次性开销会干扰数据，场景稳定后再采集。
2. **采集**：
   ```text
   mcpy --local --project <项目> --non-interactive profile capture --session <sid> --seconds 20 --json
   ```
   采集文件保存在项目 `.runtime/profiles/`，返回 `trace` 路径与报告摘要。只关心某个模块时加 `--filter <函数名或模块路径片段>`，需要更多条目加 `--top 30`。已有文件可用 `profile report <trace> --json` 重新汇总。
3. **读摘要**：
   - `main_loop`（`Main Update`，即客户端帧）与 `server_tick`（`serverUpdate`）：次/秒与 p50/p95/p99/最大耗时，先判断问题是持续偏慢（p50 高）还是偶发卡顿（p99/最大高）。
   - `script`：脚本自身耗时（ms/秒）和脚本调用的内置函数耗时，衡量脚本整体占用。
   - `scripts`：脚本函数按总耗时排序，含 `source`（项目内源码路径）、`line`、调用者、所在线程。`self_ms` 高表示函数体本身慢；总耗时高而自身低时看它调用的函数（用 `--filter` 收窄）。
   - `script_spikes`：按单次最大耗时排序，用于定位偶发卡顿。
   - `engine`：引擎区段按自身耗时排序。
   - `windows`：最慢若干次主循环与服务端 tick，列出该时间段内各线程自身耗时最多的区段，所在线程的条目优先。
4. **修改并验证**：保持同一场景和相近采集时长，重新采集，然后
   ```text
   mcpy --local --project <项目> --non-interactive profile diff <修改前.tracy> <修改后.tracy> --json
   ```
   对比按每秒耗时计算（时长可不同）。结论以目标函数的 ms/秒和主循环分位数为准，变化不明显时重复采集确认，不凭一次数据下结论。
5. **报告**：给出平台、运行包或引擎版本、场景、采集时长、关键函数（源码:行号）的前后数据。

## 解读注意

- 每次 Python 调用都会记录，开销会放大调用频繁的小函数；看相对排名和前后变化，不把单个区段耗时当作无分析时的真实耗时。
- 内置函数（如 `time`、`len`）单独成区段，位置是模块名、行号 0；它们的耗时不计入调用者的 `self_ms`。
- `prepareFrame` 的自身耗时包含帧率等待；`sleep` 等等待类区段不是计算。其他线程里的等待出现在慢帧窗口中，不代表它导致了卡顿。
- 游戏每帧打两次帧标记，帧时间以 `Main Update` 为准。
- macOS 的渲染耗时受图形转译影响，不能当作 Windows 的结论；脚本函数的相对耗时可以参考。
- 返回 `protocol_mismatch` 表示游戏内置 Tracy 已变化：停止并报告游戏版本，不要换用其他 Tracy 版本重试。

## 人工使用

```text
mcpy profile install                  # 准备工具
mcpy profile status                   # 工具状态与本机正在监听的游戏（不连接游戏）
mcpy profile open --session <sid>     # 实时分析器，连接运行中的游戏；只有一个游戏时可省略 --session
mcpy profile open <文件.tracy>         # 离线打开采集文件
mcpy profile capture --session <sid> --seconds 20
mcpy profile report <文件.tracy>
mcpy profile diff <修改前.tracy> <修改后.tracy>
```

实时分析器关闭窗口后才能再次采集。采集文件可直接用 `profile open` 离线查看时间线、调用栈和统计。

## 错误

| code | 含义与处理 |
|---|---|
| `profiler_tools_missing` | 运行 `mcpy profile install` |
| `download_failed` | 网络失败，进度已保留；重试、设置 `MCPY_TRACY_MIRROR` 或 `--from` 导入 |
| `integrity_error` | 下载或导入的工具包与清单不一致，已拒绝安装 |
| `unsupported_platform` | 仅支持 Apple Silicon macOS 与 Windows x64 |
| `profiler_unavailable` | 游戏未监听；等待数秒，或检查 macOS 运行包版本 |
| `ambiguous_target` | 多个游戏实例，用 `--session` 或 `--port` 指定 |
| `profiler_busy` | 已有分析器连接；由用户关闭后重试 |
| `protocol_mismatch` | 游戏 Tracy 版本已变化；停止并报告 |
| `capture_failed` | 采集未完成；确认端口未被占用后重试 |
