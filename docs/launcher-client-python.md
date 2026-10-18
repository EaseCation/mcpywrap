# macOS Launcher 本地控制协议

日常 Python 调试用法见内置 Skill 的[运行时调试](../skills/mcpywrap/references/runtime-debug.md)，截图用法见[画面采集](../skills/mcpywrap/references/capture.md)。本文维护原生接口与宿主实现的边界，不作为另一套用户操作指南。

## 通道与身份

Launcher 在私有临时目录建立 Unix socket，并在实例 data 目录原子发布 `python-control.json`：protocol=1、pid 和 socket 路径。元数据为 0600，socket 所在目录为 0700；宿主核验归属、权限及会话进程身份，不按窗口标题选目标。Python 与截图共享传输实现，方法独立，截图不执行游戏 Python，也不占 Python 请求队列。

`status` 只读返回原生能力和 Python 就绪状态。`screenshot_protocol=1` 同时记录在运行包 runtime.json 和实际进程 status 中；前者供实例能力查询，后者在截图前确认运行中的实现。查询能力不触发读帧。

## 客户端 Python

`submit/result/cancel/release` 按 request_id 管理请求。相同 ID 与内容幂等，不同内容拒绝；排队请求可取消，已执行的游戏代码不能强行回滚。Python 未就绪时排队，进入世界后保留同一客户端命名空间。外层 worker 继续管理用户可见结果、并发和 Safaia 服务端通道。

JSON UI 定义重载由独立的 `json_ui_reload_protocol=1` 声明。重载后业务界面与回调由 Mod 原有逻辑重新注册；协议不替代资源部署与会话占用检查。

## 单帧截图

`screenshot` 方法接受 `{op, request_id}`；op 为 capture、poll、release，ID 为 32 位小写十六进制。每进程只有一个槽位。capture 幂等，poll 不创建请求，release 只取消/释放匹配 ID，读取已开始时延迟回收其内存。

请求在下一次 GLES swap 前、Launcher 工具层绘制前读取游戏 framebuffer，去掉顶部菜单栏，输出游戏内容区物理像素。原生端保留并恢复 framebuffer/pixel-pack 状态。五秒内没有完成有效读回返回 capture_timeout；不回退系统屏幕采集，不改变前台窗口。

RPC 线程预留有界的匿名内存（最多 16 MiPixels × 4 字节）。渲染线程写入 bottom-up RGBA；完成后 RPC 线程写入私有像素文件并返回 width、height、source_time_ns。磁盘满通过 IO 错误返回，不将文件映射作为 GL 目标，以免渲染线程触发 SIGBUS。该时间来自 Launcher steady_clock，不是 Unix 时间，也不保证与 GPU 呈现时刻相同。

像素路径固定为 socket 目录下的 `screenshot-<request_id>.rgba`，不接受调用方提供的原生输出路径。宿主以 no-follow 打开，检查归属、权限、类型和精确大小，完成方向/颜色转换与 PNG 编码。命令结束总是尝试 release；失联请求最多占用一个槽位，30 秒租约过期后可由下一请求回收，正常进程退出清理。

原生实现只采集单帧，没有编码队列、持续采集服务或录像能力。macOS 的 record/record-frames 保持不支持。运行包必须重新构建才能提供新协议；更新 CLI、Skill 或 runtime install 不会替换旧实例固定的原生包。
