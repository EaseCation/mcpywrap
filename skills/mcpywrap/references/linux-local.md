# AArch64 Linux：资源与平台差异

仅在安装/升级资源、解释平台能力或排查显示问题时读本页。日常启动、世界保留和部署规则与 macOS 相同，见[本地生命周期](local-development.md)；资源安装、实例固定版本与升级规则同[macOS 平台](macos-local.md)，本页只列 Linux 的不同点。

## 要求与安装

```text
mcpy --local doctor --capabilities --json
mcpy --local engine doctor --json
mcpy --local --non-interactive engine install --json
```

需要 linux-local-worlds 能力：AArch64、glibc（不支持 musl）、Wayland 或 X11 图形会话、GLES 3 驱动。x86_64 Linux 没有原生后端，可用 --remote 连接 Windows 服务。运行包声明 minimum_glibc，低于该版本时安装前拒绝（os_too_old）；64 KiB 页内核无法加载游戏库。

资源默认位于 `$XDG_DATA_HOME/mcpy`（缺省 `~/.local/share/mcpy`），MCPY_ENGINE_HOME 可隔离。运行包不签名，以 SHA-256 清单校验；与 macOS 一样，首次 run 缺资源时自动安装，APK 从网易 pe 动态发现。

## 显示会话

游戏需要当前用户的图形会话。engine doctor 返回 `display`：

- `state=display_unavailable`：没有 WAYLAND_DISPLAY/DISPLAY，或变量指向的套接字不存在。通过 SSH 运行时设置 `XDG_RUNTIME_DIR=/run/user/<uid>` 与 `WAYLAND_DISPLAY`（或 `DISPLAY`）指向已登录的桌面；不要自行启动新的合成器替用户“修复”。
- `display.warning` 提示没有可访问的 `/dev/dri/renderD*`：会退回软件渲染，确认用户在 render/video 组。
- 无显示器的测试机可用 wlroots 无头后端（labwc + `WLR_BACKENDS=headless`）并开启 linger，见运行包仓库 docs/linux-runtime.md。

PySide6 在 Linux 是可选依赖（aarch64 wheel 需要 glibc 2.39+）。未安装时后端不声明 project-ui，交互式 run 使用终端视图；需要图形调试窗口时自行 `pip install PySide6-Essentials`。Qt 界面需要系统中文字体（如 fonts-noto-cjk），精简系统缺字体时中文显示为方框。Wayland 不允许应用自行置顶，调试小窗可能位于游戏窗口之下，由合成器切换。

## 平台能力边界

| 能力 | 当前边界 |
|---|---|
| 本地世界 / 世界参数 / 游戏 Python / JSON UI 重载 | 与 macOS 0.4.8 运行包相同的协议；JSON UI 修改后重建界面已验证生效（规则同 macOS：重载后须重新创建界面）；Map 尚未接入 |
| 网络隔离 | 离线世界由运行包进程内网络守卫约束游戏代码，只放行回环；无认证联机额外放行解析出的服务器 UDP 端点。不是内核沙箱，不覆盖直接系统调用 |
| 无认证网络 | network_connect_protocol=1；服务器须允许开发客户端 |
| 游戏截图 | screenshot_protocol=1，按需读取游戏帧，与窗口系统无关 |
| 后台窗口 | background_window_protocol=1：启动器不主动聚焦、不抢占指针。Wayland 由合成器决定焦点，实测 labwc 仍会激活新开的游戏窗口；需要完全不打扰当前桌面时使用独立会话或无头合成器 |
| Tracy | 仅 127.0.0.1:8086；运行包默认关闭 perf 系统采样（TRACY_NO_SYS_TRACE=1）。linux-arm64 工具包发布前，用仓库 native/tracy_tools/build.py 在本机构建，再 `profile install --from <zip>` 导入（校验包内版本、协议、平台与逐文件摘要，status 标记 source=local-import）；采集与报告用法同[性能分析](profiling.md) |
| Shader 热更 | 返回 unsupported，重新部署并重载世界 |
| 本地主客机、MCS 身份、MCEditor、录屏、原始设备输入 | 不支持 |

画面、音量和输入偏好保存在资源根 `preferences/linux`。

已实机验证：树莓派 5（Debian 13、16 KiB 页、V3D、Wayland）与 Ubuntu 22.04（glibc 2.35、4 KiB 页、X11、Mesa llvmpipe 软件渲染）。其他 GPU 驱动与带窗口管理器的 X11 桌面未验证，遇到问题时先看 engine.log 的 `[GL] Renderer` 与 glfwInit 错误原因。
