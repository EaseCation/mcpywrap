# 游戏截图、录制、窗口尺寸与逐帧检查

用于截图、录像、固定画面分辨率或提取游戏画面；仅截图时读完下一节即可。远程服务配置另见[远程执行端](remote-testing.md)。


## 截图

```text
mcpy --local --project <项目> --non-interactive screenshot --session <sid> --background-only --output <新的PNG路径> --json
```

Windows 和 macOS 使用相同命令。远程将 --local 替换成 --remote <Windows HTTP endpoint>，返回的 image 是调用端路径。截图为游戏内容区物理像素，不含系统标题栏；组内操作明确选择成员 session。

不占用前台的任务保留 --background-only。后台启动的会话会强制仅后台捕获。普通前台会话的 Windows 默认截图可能从 WGC 后台捕获回退可见窗口；后台捕获失败时不能移除该参数、激活游戏或用前台截图冒充后台结果。

macOS 需要目标实例的运行包支持 `screenshot_protocol=1`，用 `runtime capabilities --session <sid> --json` 的 screenshot 状态检查。旧包返回 capability_missing；更新 CLI 或 Skill 不会升级实例绑定，按[平台页](macos-local.md)选择支持该协议的运行包和新实例。

macOS 从 Launcher 按需读取下一帧，不需要屏幕录制授权或 runtime install；返回 capture=launcher-framebuffer、coordinate_space=game-content。图像去掉 Launcher 菜单栏及其工具浮层，不含系统光标或桌面。两种 background-only 设置均不抢前台、不回退桌面采集。每会话同时一个请求，等待渲染最多约 5 秒，像素上限 16 MiPixels；busy 时等待，capture_timeout 时确认游戏仍在渲染。最小化、锁屏、暂停渲染不保证有新帧，不用高频截图循环模拟录像。

需要允许占用前台的旧 Windows 桌面输入时才读[兼容输入](input-writing.md)；日常 UI/玩家操作读[统一输入](runtime-input.md)。

## 窗口尺寸与画面分辨率

游戏按窗口客户区像素渲染，窗口尺寸就是截图、录像和指针坐标的分辨率。需要固定分辨率时在启动时指定，或对运行中的会话调整（CLI 0.8.1+）：

```text
mcpy --local --project <项目> --non-interactive run --no-gui --detach --window-size 1280x720 --json
mcpy --local --project <项目> --non-interactive window info --session <sid> --json
mcpy --local --project <项目> --non-interactive window resize --session <sid> --size 1920x1080 --json
```

- 尺寸为不含标题栏的客户区物理像素，320x240–7680x4320；`run`、`connect`、`--clients 2`（两个客户端相同）都接受 `--window-size`。macOS 已实测窗口、游戏帧缓冲截图和录像三者尺寸一致，调整后游戏立即按新尺寸渲染。
- 启动时的尺寸由会话 worker 在游戏窗口出现后经系统 API 设置；`run --detach` 返回时 `window.state=pending`，之后在 `status --session <sid> --json` 的 `window` 查看 `applied` 或 `failed`（含 code/hint）。失败不终止游戏。进入游戏前游戏若自行改回尺寸会补设，最多 3 次。
- restart、组重启和成员重试沿用启动时的尺寸；`window resize` 只改当前窗口，不改变记录的启动尺寸，并且之后不再补设启动尺寸。`run --window-size` 复用已运行的会话时直接调整该窗口，结果在返回的 `window`。
- 调整保持窗口位置，不激活窗口、不移动光标，后台会话可用；全屏（window_fullscreen）、Windows 最大化或最小化（window_state_conflict）时拒绝，先还原窗口。系统或游戏未采用请求尺寸时返回 window_size_rejected 和实际尺寸，常见于超出屏幕可用区域。录制中拒绝调整（busy），改变尺寸会结束录像；截图期间尺寸变化会使该次截图失败。
- Windows 经 SetWindowPos，DPI 缩放下仍按物理像素。macOS 经辅助功能 API，需要在“系统设置 > 隐私与安全性 > 辅助功能”允许运行 mcpy 的终端或宿主应用（与 macos-cgevent 输入相同），未授权返回 permission_missing；`doctor --capabilities` 的 `media.window_resize_permission` 报告授权。Retina 显示器缩放为 2 倍时宽高须为偶数（invalid_size）；`window info` 的 `scale` 为当前显示器缩放。只读的 `window info` 不需要授权。
- 远程 Windows 服务声明 `window-size` 能力后，`--remote` 同样可用于 `connect --window-size` 与 `window info/resize`。App 宿主的画面由 App 决定，不接受这些参数。

## 视频录制与逐帧分析

Windows 本机或远程 Windows，以及 Apple Silicon macOS 本机（CLI 0.8.0+）都提供同一组 `record` 命令。录制任务先检查执行端 `record` 和 `record-frames` 能力；bootstrap 可重复传入 `--require-capability`。新版 Skill 不代表旧 CLI 或旧原生组件支持录制。视频文件在执行端临时目录持续写入，下载到调用端；无需安装 FFmpeg。

macOS 使用随 CLI 安装的 ScreenCaptureKit 辅助程序（开发签名），游戏窗口可留在后台或被遮挡，不激活窗口、不移动光标；画面为不含标题栏的客户区（与 Windows 一致）；最小化、关闭或改变窗口尺寸会结束录像（`end_reason`），需要固定分辨率时先按[窗口尺寸](#窗口尺寸与画面分辨率)设置再录。首次使用需在“系统设置 > 隐私与安全性 > 屏幕录制”中允许运行 mcpy 的终端或宿主应用，并重启该应用；未授权时 `doctor --capabilities` 的 `media.screen_capture_permission=false`、`record_available=false` 并给出原因，工具不弹窗、不绕过授权。

```bash
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record start --session <sid> --duration 10 --fps 30 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive runtime input run --session <sid> --file <移动计划.json> --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record status --session <sid> --recording <rid> --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record download --session <sid> --recording <rid> --output ./captures/clip.mp4 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record frames --session <sid> --recording <rid> --frame 0 --frame 30 --output ./captures/frames --json
```

移动计划使用 steps=[{"action":"player.move","forward":1,"duration_ms":2000}]；先完成 runtime install，再input observe确认HUD与玩家状态。保存 start 返回的 `recording` 作为 rid，保持同一 endpoint、project 和 session。start 在首帧写入后返回，随后可同时执行运行时动作；查询至 `completed` 再下载／提帧。返回 `video/images/manifest` 是调用端路径。Windows 本机将全局路由替换为 `--local --project "<Windows项目>"`，其余参数相同。

时长为整数 1–300 秒，帧率为整数 1–60 FPS，默认 10 秒／30 FPS，无音频。每个会话一次录制。固定视频帧可能重复源画面或跳过游戏呈现画面，不能据此保证完整捕获游戏每一帧；PNG 是编码后画面。检查清单中的 `frame/time/source_time/repeated`，查看下载的 PNG，再结合日志判断逻辑是否通过。

`time` 是视频内的秒数；`source_time` 是执行端单调时钟秒数（Windows 为 WGC 帧时间，macOS 为 ScreenCaptureKit 帧的 mach 主机时钟，与 `runtime input` 的 `launcher.steady_clock` 同源），不是 Unix 时间，原始值保留在 `source_time_100ns`。macOS 以 1/120 秒的最小间隔采集游戏渲染的每一帧，再按源帧时间挑选最接近每个输出时刻的画面；`frames_captured` 只统计内容有变化的源画面，`source_frames_skipped` 为未写入视频的源画面数。高分辨率／高帧率可能超过机器编码能力，`encoder_too_slow` 时降低帧率或使用较小游戏窗口，不通过隐藏丢帧将失败当作完成。

提帧 `--frame` 从 0 开始，可重复，单次最多 100 个；也可改用重复的 `--at <秒>`，取 `floor(秒 × fps)`，两者互斥。输出目录及 MP4 路径必须不存在。需要连续分析时分批选择帧，避免一次提供全部图片。

提前结束使用 `record stop`，不停止游戏；游戏结束也会结束录像。短片若成功封装仍可下载，检查 `truncated/end_reason`。start 超时先用 `record status --session <sid> --list` 找回，不盲目重录；显式 `--request-id <32位小写hex>` 可找回同一请求。下载中断可重试到尚不存在的目标路径。

执行端产物完成后保留 24 小时，后续命令或服务启动清理过期文件；游戏退出后仍可下载。任务结束且文件已下载后可执行 `record delete --session <sid> --recording <rid>`，仅删除执行端产物。异常处理见[故障定位](troubleshooting.md#录制与提帧)。


服务只接受归属该会话的录制 ID。MP4/提帧 ZIP 下载校验后发布调用端文件，断线可重试到尚不存在的目标，不支持断点续传。starting/recording/finalizing 不能下载；completed 可下载，failed/interrupted/cancelled 无可发布视频，expired/deleted 无产物。

窗口最小化、锁屏、关闭、尺寸变化或持续没有采集帧可能结束录制，不自动回退桌面捕获；正常遮挡也可能因游戏暂停渲染而结束。排查见[录制故障](troubleshooting.md#录制与提帧)。
