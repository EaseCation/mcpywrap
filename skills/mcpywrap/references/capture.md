# 游戏截图、Windows 录制与逐帧检查

用于截图、录像或提取游戏画面；仅截图时读完下一节即可。远程服务配置另见[远程执行端](remote-testing.md)。


## 截图

```text
mcpy --local --project <项目> --non-interactive screenshot --session <sid> --background-only --output <新的PNG路径> --json
```

Windows 和 macOS 使用相同命令。远程将 --local 替换成 --remote <Windows HTTP endpoint>，返回的 image 是调用端路径。截图为游戏内容区物理像素，不含系统标题栏；组内操作明确选择成员 session。

不占用前台的任务保留 --background-only。Windows 默认截图可能从 WGC 后台捕获回退可见窗口；后台捕获失败时不能移除该参数、激活游戏或用前台截图冒充后台结果。

macOS 需要目标实例的运行包支持 `screenshot_protocol=1`，用 `runtime capabilities --session <sid> --json` 的 screenshot 状态检查。旧包返回 capability_missing；更新 CLI 或 Skill 不会升级实例绑定，按[平台页](macos-local.md)选择支持该协议的运行包和新实例。

macOS 从 Launcher 按需读取下一帧，不需要屏幕录制授权或 runtime install；返回 capture=launcher-framebuffer、coordinate_space=game-content。图像去掉 Launcher 菜单栏及其工具浮层，不含系统光标或桌面。两种 background-only 设置均不抢前台、不回退桌面采集。每会话同时一个请求，等待渲染最多约 5 秒，像素上限 16 MiPixels；busy 时等待，capture_timeout 时确认游戏仍在渲染。最小化、锁屏、暂停渲染不保证有新帧，不用高频截图循环模拟录像。

需要允许占用前台的旧 Windows 桌面输入时才读[兼容输入](input-writing.md)；日常 UI/玩家操作读[统一输入](runtime-input.md)。

## 视频录制与逐帧分析

**macOS 本地不支持录屏和视频提帧。** Mac 可作为客户端调用远程 Windows。录制任务先检查执行端 `record` 和 `record-frames` 能力；bootstrap 可重复传入 `--require-capability`。新版 Skill 不代表旧 CLI 或旧原生组件支持录制。视频文件在 Windows 临时目录持续写入，下载到调用端；无需安装 FFmpeg。

```bash
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record start --session <sid> --duration 10 --fps 30 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive runtime input run --session <sid> --file <移动计划.json> --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record status --session <sid> --recording <rid> --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record download --session <sid> --recording <rid> --output ./captures/clip.mp4 --json
mcpy --remote <endpoint> --project "<调用端项目>" --non-interactive record frames --session <sid> --recording <rid> --frame 0 --frame 30 --output ./captures/frames --json
```

移动计划使用 steps=[{"action":"player.move","forward":1,"duration_ms":2000}]；先完成 runtime install，再input observe确认HUD与玩家状态。保存 start 返回的 `recording` 作为 rid，保持同一 endpoint、project 和 session。start 在首帧写入后返回，随后可同时执行运行时动作；查询至 `completed` 再下载／提帧。返回 `video/images/manifest` 是调用端路径。Windows 本机将全局路由替换为 `--local --project "<Windows项目>"`，其余参数相同。

时长为整数 1–300 秒，帧率为整数 1–60 FPS，默认 10 秒／30 FPS，无音频。每个会话一次录制。固定视频帧可能重复源画面或跳过游戏呈现画面，不能据此保证完整捕获游戏每一帧；PNG 是编码后画面。检查清单中的 `frame/time/source_time/repeated`，查看下载的 PNG，再结合日志判断逻辑是否通过。

`time` 是视频内的秒数；`source_time` 是 Windows 单调时钟秒数，不是 Unix 时间，原始值保留在 `source_time_100ns`。高分辨率／高帧率可能超过机器编码能力，`encoder_too_slow` 时降低帧率或使用较小游戏窗口，不通过隐藏丢帧将失败当作完成。

提帧 `--frame` 从 0 开始，可重复，单次最多 100 个；也可改用重复的 `--at <秒>`，取 `floor(秒 × fps)`，两者互斥。输出目录及 MP4 路径必须不存在。需要连续分析时分批选择帧，避免一次提供全部图片。

提前结束使用 `record stop`，不停止游戏；游戏结束也会结束录像。短片若成功封装仍可下载，检查 `truncated/end_reason`。start 超时先用 `record status --session <sid> --list` 找回，不盲目重录；显式 `--request-id <32位小写hex>` 可找回同一请求。下载中断可重试到尚不存在的目标路径。

执行端产物完成后保留 24 小时，后续命令或服务启动清理过期文件；游戏退出后仍可下载。任务结束且文件已下载后可执行 `record delete --session <sid> --recording <rid>`，仅删除执行端产物。异常处理见[故障定位](troubleshooting.md#录制与提帧)。


服务只接受归属该会话的录制 ID。MP4/提帧 ZIP 下载校验后发布调用端文件，断线可重试到尚不存在的目标，不支持断点续传。starting/recording/finalizing 不能下载；completed 可下载，failed/interrupted/cancelled 无可发布视频，expired/deleted 无产物。

窗口最小化、锁屏、关闭、尺寸变化或持续没有采集帧可能结束录制，不自动回退桌面捕获；正常遮挡也可能因游戏暂停渲染而结束。排查见[录制故障](troubleshooting.md#录制与提帧)。
