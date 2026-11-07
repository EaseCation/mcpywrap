# Tracy 分析工具包

`mcpy profile` 使用的分析器、采集和报告工具。游戏内置 Tracy 0.11.1（协议 69），分析器必须同版本，因此从固定源码构建、单独发布，由 mcpywrap 按 `core/mcpywrap_core/profiling/tools.json` 下载校验。用户用法见 [性能分析](../../skills/mcpywrap/references/profiling.md)。

## 内容

每个平台一个 ZIP（`mcpy-tracy-0.11.1-<构建号>-<平台>.zip`），根目录 `mcpy-tracy/`：

- `tracy-profiler`：实时与离线分析器界面。
- `tracy-capture`：无界面采集。
- `tracy-csvexport`：Tracy 自带 CSV 导出。
- `mcpy-tracy-report`：本目录 `report/` 的 JSON 报告工具，基于同版本 TracyServer，输出区段统计与分位数、调用边、线程、帧标记，以及主循环/服务端 tick 最慢实例内按线程的自身耗时归因。
- `LICENSE`（Tracy，BSD-3-Clause）与 `BUILDINFO.json`（版本、源码提交、协议、各文件 SHA-256）。

依赖（capstone、glfw、freetype）由 Tracy 的 CPM 下载并静态链接，不使用构建机上的 Homebrew/pkg-config 动态库。macOS 产物最低 13.0、ad-hoc 签名；Windows 静态链接 MSVC 运行库，只依赖系统 DLL。

## 构建

```sh
python native/tracy_tools/build.py --work <构建目录> --output <输出目录> [--source <Tracy 检出>] [--build 1]
```

源码不存在时按 `v0.11.1` 克隆，并核对提交 `5d542dc09f3d9378d005092a4ad446bd405f819a`。构建前只做编译兼容修正（`TracyView.hpp` 补充 `#include <chrono>`，新版 MSVC 需要），不改变行为，修正列表记录在 `BUILDINFO.json` 的 `source_fixes`。输出 ZIP 与同名 `.json`（平台、文件名、大小、sha256）。支持 Apple Silicon macOS 与 Windows x64。

## 发布

1. 工作流 [`tracy-tools.yml`](../../.github/workflows/tracy-tools.yml) 可手动运行，只构建并上传 artifact，用于验证。
2. 推送标签 `tracy-tools-0.11.1-<构建号>` 后两平台构建，并创建同名 GitHub Release（不标为 Latest），附 ZIP、`platforms.json` 与 `SHA256SUMS`。
3. 把 `platforms.json` 的内容写入 `tools.json` 的 `platforms`，`build` 与镜像地址同步为该构建号，随 mcpywrap 版本发布。已发布的 ZIP 不覆盖；变更内容使用新的构建号。

更换 Tracy 版本只在游戏内置版本变化时进行：同时更新 `build.py` 的版本、标签、提交和协议，`report.cpp` 的版本字符串，以及 `tools.json`。
