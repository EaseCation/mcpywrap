# macOS 运行包内置 Tracy 分析器

运行包 0.4.7 起包含本目录补丁。网易开发者版 `libminecraftpe.so` 内置 Tracy 客户端，按 `TRACY_MANUAL_LIFETIME` 构建。引擎在首次给线程命名时自行调用 `tracy::StartupProfiler()`，没有配置开关，因此运行包只需要提供正确的宿主接口，不需要也不应主动启动。启动器再调用一次 `___tracy_startup_profiler` 会产生第二个独立实例并占用下一个端口。

## 旧运行包的问题

Tracy 工作线程在监听前依次调用 `uname`、`gethostname`、`getlogin`、`sysinfo`。旧运行包中：

- `uname` 直接透传 Darwin 实现，按 5×256 字节布局写入 Bionic 调用方的 390 字节缓冲，造成栈溢出，工作线程卡死。
- `getlogin`、`sysinfo` 是 DeveloperCompat 终止桩，调用即以 53 结束进程。

结果是 `___tracy_profiler_started` 为 1 但端口从不监听。socket 层本身可用，不需要改动。

## 补丁

- `libc-shim-host-info.patch`：新增独立的 `src/host_info.cpp`（不与 `common.cpp` 共享 Darwin `sys/param.h` 宏环境）。`uname` 按字段截断转换为 Bionic 6×65 布局；新增 `sysinfo`（Darwin 取自 sysctl、Mach 虚拟内存统计与 libproc，Linux 宿主逐字段复制，其他宿主返回 `ENOSYS`）；`getlogin` 使用宿主实现。均经过 errno 转换。
- `client-tracy.patch`：DeveloperCompat 终止桩改为只填补 libc-shim 缺失的接口，已提供 ABI 转换的实现不再被覆盖；加载游戏库前默认设置 `TRACY_ONLY_LOCALHOST=1`、`TRACY_ONLY_IPV4=1`，已存在的环境变量优先。
- `manifest-tracy.patch`：`tests/libc_host_info.cpp` 以保护区校验三个接口不越界写入并返回有效值，纳入构建脚本的 CTest。
- `apply.py`：三份补丁全部预检后才应用，已应用项跳过，失败回滚；不下载、构建或启动游戏。

修复按符号进行，不含游戏版本相关的地址或偏移；新 APK 只要通过标准 libc 导入调用这些接口即可直接受益。

核对基线：manifest `8b624579618a121c345dd4ff05748d426a0141fa`，client `350eb36f499fbb4bc2bcaf413bd7b2fefa1fb782`，libc-shim `8ca149814eba0c42fa0c1f945b76fb526f6f0694`。可与 [后台窗口补丁](../background_window/README.md) 同时应用，两者不修改相同的位置。

## 构建

源码准备与 [后台窗口补丁](../background_window/README.md#在-mac-构建测试包) 相同，额外执行：

```sh
python3 native/tracy_profiler/apply.py --manifest /path/to/runtime-source
```

然后用 `tools/build_macos_runtime.py` 构建新的运行包。Xcode SDK 升级后，旧 CMake 构建目录可能仍引用已删除的 SDK 路径，此时使用新的 `--build-dir`。

## 连接与安全

- 默认监听 `127.0.0.1:8086`；端口被占用时顺延到 8087–8105（例如多个本地实例）。
- 需要从其他设备连接时，显式以 `TRACY_ONLY_LOCALHOST=0 TRACY_ONLY_IPV4=0` 启动；这会对所有网卡开放分析端口并发送 UDP 发现广播，只在可信网络使用。
- viewer 版本必须与游戏内置 Tracy 的协议一致，协议随游戏版本变化。`probe.py` 是可选手动工具，列出本机端点及其协议号：

```sh
python3 native/tracy_profiler/probe.py
```

开发者包 3.9.100.297020 内置 Tracy 0.11.1，协议 69。

## Mac 验收

1. 用新运行包创建独立实例，确认引擎日志中没有 `Unimplemented Android interface`。
2. `lsof -nP -a -p <pid> -iTCP -sTCP:LISTEN` 只出现 `127.0.0.1:8086`（单实例）。
3. `probe.py` 返回 `status=welcome` 及协议号；用对应版本的 Tracy viewer 连接 `127.0.0.1` 并看到帧与区段数据。
4. 以 `TRACY_ONLY_LOCALHOST=0` 启动时监听地址变为通配地址，未设置时不会出现。
