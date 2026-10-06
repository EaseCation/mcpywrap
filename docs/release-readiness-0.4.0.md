# 0.4.0 正式发布核查与合并计划

核查日期：2026-10-06（Asia/Shanghai）。核查后用户已授权正式发布；最低 macOS 统一调整为 13.0。

后续执行：原生运行包以 `mcpy-runtime-v0.4.0` 发布，mcpy 默认目录切换到正式 URL，PR #3 合入 main 后由 v0.4.0 标签发布。以下核查条目保留原始背景；正式结果以 GitHub Release、PR 和 PyPI 为准。

## 发行物与自动化

| 发行物 | 准备方式 | 发布入口 |
| --- | --- | --- |
| mcpy wheel/sdist | mcpywrap release.yml：Windows 原生编译 → Windows 3.9/3.12/3.14 与 macOS 测试 → Linux 打包、安装验收 | main 上匹配版本的 v0.4.0 标签，或 main 的手动 publish=true；上传 PyPI |
| Windows 登录桥接、截图/录制程序 | CI 用 MSVC 编译；登录桥接在 main/tag 使用已配置的项目证书签名 | 包含在 wheel/sdist；普通候选分支产物未签名 |
| macOS ARM64 运行包、完整对应源码、catalog、SHA256SUMS | manifest 的 mcpy-runtime.yml；手动启动 CI 后自动构建/审计/打包 | publish=false 仅 artifact；publish=true 且 prerelease=false 创建正式 GitHub Release |
| ANGLE 和 Android 支持库 | 复用上游固定版本预构建内容，ANGLE 下载有 SHA-256 校验；不依赖本机 Launcher | 集成到 macOS 运行包，保留许可证与来源 |
| 网易开发者 APK | 客户端从网易官方 CDN 获取固定版本并验证摘要 | 不上传到我们的 GitHub/PyPI |
| PySide6/Qt6 | 由 Python 包管理器安装兼容的官方 wheel | 不打入 mcpy wheel，不需要自编译 Qt |

当前公开运行包是 `mcpy-runtime-v0.4.0-preview.1`，含 3.10.100.299889 profile。目录和原生包可匿名下载，对应源码和摘要已公开。Python 0.4.0 尚未上传 PyPI；当前正式版为 0.3.19。默认安装入口仍固定到该 preview，正式发行前需选择最终运行包版本并更新 DEFAULT_CATALOG。

本地编译仅作为排障/备用路径，不应成为每次发行的前提。`build_macos_runtime.py` 支持 CMake 4 的旧子项目 policy，并在失败时输出日志；CI 同时保存详细诊断。原生 CI 不下载游戏或运行游戏，构建成功不能替代真机验收。

## 本次发现并处理

- 旧候选 CI 在 Windows Python 3.9 / PySide 6.10 崩溃：本机同版本复现，原因是测试替换 QObject 类方法触发 Qt 绑定层问题。已改为真实对话框确认/取消测试。
- Python 3.9 使用 Click 8.1，测试 runner 默认合并 stderr；已使用兼容配置分离 JSON 与进度输出。
- macOS 原生 CI 首次执行发现 CMake 4 不接受 simple-ipc 的旧 minimum 版本。构建入口统一设定兼容 policy，无需为此扩大上游子模块差异。
- macOS 工作流原来只能发布 prerelease；现提供显式的正式发行开关，默认仍仅构建，不发布。

## 合并顺序

1. 等候选代码在 Windows 3.9/3.12/3.14、macOS 和 wheel/sdist 构建检查全部通过，取得可安装候选 wheel。重点在 Windows 真机复测本轮新增的 v2 依赖锁、run 调试小窗与关闭/热更操作。
2. 保持五个修改后的子模块 fork 的 `netease-macos-arm64` 分支；已核对 manifest 锁定提交与公开分支一致。它们已是我们的适配主线，无需合并到 upstream/ng 或上游 master。
3. manifest 的 `netease-macos-arm64` 同样作为发行主线。先运行 publish=false 的原生 CI，用产物在本机验证安装、进入世界、Python/热更和保存退出。
4. 确认签名路线与实际支持的 macOS 范围后，通过同一 workflow 发布不可变正式运行包（例如 mcpy-runtime-v0.4.0；publish=true、prerelease=false）。运行包和对应源码必须同时发布，不覆盖 preview 资产。
5. 在 mcpy 候选分支把 DEFAULT_CATALOG 改为该正式地址，验证公开源安装，再更新发行记录。保持 Python 两处版本一致为 0.4.0。
6. 创建 `codex/0.4.0-cross-platform → main` PR，以正常 merge 保留可追溯历史。核查时 main 未领先候选分支，可直接合并；临近合并仍重新核对远端与检查结果。
7. main CI 使用正式 Windows 签名，检查完整 wheel。验收通过后在该 main 提交推送 v0.4.0，触发签名构建和 PyPI Trusted Publishing。普通 push main 不发布；不要同时使用标签和手动发布重复上传同一版本。
8. 发布后从干净 Python 环境安装 PyPI 包；Windows 使用用户已安装的 MC Studio，macOS 走默认在线安装，检查 doctor、run、日志/热更与退出。GitHub Release 与 PyPI 版本不能原地替换，失败修复使用新版本。

## 仍需正式验收的边界

- 本机验证环境为 macOS 26.6.2；运行包 Mach-O 部署目标 11.0 不等于完整 GUI 的支持下限。Qt wheel 还有自己的系统要求，需明确最终支持范围并在最低版本真机或 VM 验证。
- 当前 macOS 原生包为 ad-hoc 签名，没有 Developer ID 公证。CLI 下载路线不天然要求 DMG 或 Apple 证书，但尚未完成干净用户环境的系统安全提示验收；保留此路线或接入公证需在正式发行前明确。
- 最近一次完整安装验收的原生包来自公开下载，APK 因 CDN TLS/速度问题复用了已校验缓存；不能据此宣称干净网络下全量自动下载已验收完成。
- CI 不具备真实 Minecraft/MC Studio 桌面会话，无法替代可选原生输入/录制测试、MCS 签名登录测试及玩法实测。
- GitHub 的 main 目前没有分支保护，pypi environment 没有人工审批规则。现有工作流有版本、main 祖先关系、签名与依赖任务门槛；合并和打标签仍由发布者按上述顺序执行。

签名 secrets 仅检查了名称，未读取私钥。仓库公钥有效期至 2028-09-27。v0.3.19 的签名构建和 PyPI publish 均有成功记录；这证明既有发布链路可用，不替代 0.4.0 的最终 main 签名构建。
