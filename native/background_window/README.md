# macOS 后台窗口运行包

CLI 的后台窗口接口需要运行包 `background_window_protocol=1`。旧包返回 `background_window_unavailable`；允许占用前台时可显式 `--foreground`。这些补丁针对源码构建，不修改已签名应用或旧实例绑定。

## 补丁与基线

- `game-window-background.patch`：在初次创建及 ES2 回退的 hints 重置后关闭 `GLFW_FOCUSED` / `GLFW_FOCUS_ON_SHOW`，后台时禁止全屏和光标锁定、隐藏、重定位。
- `client-background.patch`：跳过后台会话的全屏偏好和请求，保留用户偏好。
- `manifest-background.patch`：helper 接受 `--background`，显式传入 `MCPY_GAME_BACKGROUND=1/0`，普通运行不继承遗留环境开关；构建检查补丁后声明协议。
- `libc-shim-background.patch`：信号打断 Mach 信号量等待时转换为 `-1/EINTR`，避免退出信号破坏 Python 锁处理；manifest 补丁包含原生回归测试。
- `apply.py`：四份补丁全部预检后才应用，已应用项可跳过；不下载、构建或启动游戏。

核对基线：manifest `8b624579618a121c345dd4ff05748d426a0141fa`，client `350eb36f499fbb4bc2bcaf413bd7b2fefa1fb782`，game-window `d073c2aace1521ae32d239ca4fc26b97e4b4a27e`，libc-shim `8ca149814eba0c42fa0c1f945b76fb526f6f0694`。

## 在 Mac 构建测试包

在 Apple Silicon Mac 按 manifest 的说明准备 Xcode Command Line Tools、Python、CMake、Ninja 等依赖。可使用已有初始化的开发 checkout；首次准备使用核对基线：

```sh
git clone https://github.com/EaseCation/mcpelauncher-manifest.git /path/to/runtime-source
git -C /path/to/runtime-source checkout 8b624579618a121c345dd4ff05748d426a0141fa
git -C /path/to/runtime-source submodule update --init --recursive
python3 native/background_window/apply.py --manifest /path/to/runtime-source
```

选择尚不存在的应用和发行输出目录；APK 应与构建使用的 profile 匹配：

```sh
python3 /path/to/runtime-source/tools/build_macos_runtime.py \
  --output /path/to/background-build/McpyRuntime.app \
  --work-dir /path/to/background-build/portable \
  --build-dir /path/to/background-build/client
python3 /path/to/runtime-source/tools/package_macos_release.py \
  --runtime /path/to/background-build/McpyRuntime.app \
  --version 0.6.0-background.1 --output /path/to/background-release
mcpy --local --non-interactive engine install \
  --catalog /path/to/background-release/catalog.json --apk /path/to/developer.apk --json
```

mcpywrap 开发 checkout 同时安装 `./core` 与完整包：在开发虚拟环境执行 `python -m pip install -e ./core -e .`。安装新运行包后使用独立项目 `run --new`，旧实例不会自动换包。

## Mac 验收

1. 保持其他应用前台，执行标准 AI 命令 `mcpy --local --project <独立项目> --non-interactive run --new --no-gui --detach --json`。应返回 `background=true`；到 HUD 期间不切应用、不切 Space、不锁定光标。
2. `status` 确认 `world_ready`，`screenshot --session <sid> --output <新PNG> --json` 应获得新帧。后台会话禁止截图回退前台。
3. `runtime install` 后用统一输入的默认 `game` 后端验证游戏内动作和效果，覆盖遮挡、菜单及取消释放。`restart --session <sid> --json` 应产生新 session 并保留后台策略。
4. 停止自己的会话，再从交互终端执行普通 `mcpy run`，确认正常聚焦；显式 `run --foreground --no-gui --detach --json` 应返回 `background=false`。
5. 覆盖之前已开启全屏的偏好、光标锁定请求及 ES3→ES2 回退；后台退出后原有全屏偏好保持。

此模式保留可见窗口和 GPU 渲染，不承诺隐藏、最小化或锁屏后继续产生帧。公开启动用法见 [本地会话](../../skills/mcpywrap/references/local-development.md)。

### 可选原生回退测试

`test_window.cpp` 只用于交互式 Mac 桌面验收，不接入默认测试或游戏启动。它编译实际的 `window_glfw.cpp`，仅让第一次窗口创建返回失败，然后使用真实 GLFW/ANGLE 创建 ES2 窗口，断言回退后不聚焦、光标锁定请求被抑制、全屏请求被抑制。保持其他应用前台，并同时观察应用激活和 Space 事件；窗口属性断言本身不能证明没有短暂抢焦点。

在已完成上述构建的终端中设置 `source` 为 manifest 目录、`build` 为该次 CMake 构建目录、`runtime` 为新应用路径：

```sh
c++ -std=c++17 -I "$source/game-window/src" -I "$source/game-window/include" \
  -I "$build/_deps/glfw3_ext-src/include" native/background_window/test_window.cpp \
  "$build/game-window/libgamewindow.a" "$build/_deps/glfw3_ext-build/src/libglfw3.a" \
  -framework Cocoa -framework OpenGL -framework IOKit -framework QuartzCore \
  -o /tmp/mcpy-background-window-test
DYLD_LIBRARY_PATH="$runtime/Contents/Frameworks" /tmp/mcpy-background-window-test
```
