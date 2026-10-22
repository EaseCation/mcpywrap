# 发布流程

主分支、候选分支和 PR 运行 Windows Python 3.9、3.12、3.14 与 macOS 验证。同一个提交生成 `mcpywrap-core` 和完整 `mcpywrap`，两包版本必须一致，完整包精确依赖同版本核心。

唯一版本源：`core/mcpywrap_core/_version.py`。修改使用 `python scripts/version.py --set X.Y.Z`；预发布支持 `X.Y.ZrcN`、`aN`、`bN`。仅文档变更通常不发布。修复用补丁版本、兼容的新功能用次版本；进入 1.x 后不兼容变更提升主版本。即使只改一个包，也统一发两个同版本包。

构建命令为 `python scripts/build_distributions.py`，分别输出 `dist/core/` 与 `dist/desktop/`。每个 wheel 从对应 sdist 构建，避免上一次 build/lib 的残留文件混入。`scripts/check_release.py` 检查唯一版本、精确依赖、源码字节、可重建源码包和文件归属互不重叠；正式发布加 `--require-native`。

Windows CI 先用 MSVC 从 `native/mcs_auth` 编译 x86 登录桥接，再签名并通过构建产物交给测试和 完整桌面包打包任务；编译后的 EXE/DLL 位于 `desktop/mcpywrap_assets/`，不提交到 Git，也不进入核心 wheel。仓库只保留发布者公钥证书和指纹。
同一 native job 还会从 `native/window_capture` 编译 x64 后台截图辅助程序，生成 SHA-256 清单；测试和打包阶段校验二进制、源码及 wheel/sdist 内容。辅助程序不可用时运行时回退到前台截图。

该辅助程序同时提供 WGC 连续采集、Media Foundation H.264 MP4 编码及 PNG 提帧；截图仍保持原协议与回退行为，录制要求 WGC，不回退到桌面捕获。源码清单覆盖 cpp 与 video_capture.h，sdist 必须包含二者。系统 H.264 编解码能力通过只读探测报告，不捆绑 FFmpeg。发布前在交互式 Windows 桌面执行 `MCPY_NATIVE_TESTS=1` 的原生验收；普通 CI 跳过需要可见桌面的测试。

从源码安装时，在 Windows x64 且已安装 Visual Studio x86/x64 C++ 工具的环境中先运行 `python scripts/build_all_native.py`，再执行 `pip install -e ./core -e .` 或 `pip install ./core .`。脚本一次编译 x86 登录桥接和 x64 截图程序到包目录；可用 `--output-root <目录>` 将结果放入隔离目录。登录桥接源码编译产物没有发布签名，正式登录能力仍应使用带签名的发布包。

仓库 Actions secrets：`MCS_BRIDGE_SIGNING_PFX` 保存 Base64 编码的加密 PFX，`MCS_BRIDGE_SIGNING_PASSWORD` 保存独立的强密码。只有 main／发布标签的签名步骤可读取它们，PR 只构建未签名测试产物。CI 将证书导入临时 runner 的个人证书库，签名后清理，不安装根信任。私钥、PFX 和密码均不进入日志或 artifact。

轮换签名身份时，需要同时更新这两个 secrets 和 `native/mcs_auth/publisher.cer`、`publisher.json`。脚本会拒绝与仓库固定公钥不匹配的签名证书；未签名产物不能进入 PyPI 发布任务。

发布凭据使用 PyPI Trusted Publishing，不在仓库或工作流中保存长期 API token。在 PyPI 项目 `mcpywrap-core` 和 `mcpywrap` 各自的 Publishing 设置添加 GitHub publisher：

| 字段 | 值 |
|---|---|
| Owner | `EaseCation` |
| Repository | `mcpywrap` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

每次发布：

1. 使用 `python scripts/version.py --set X.Y.Z` 修改唯一版本源，并更新 CHANGELOG。
2. 将通过本地验证的提交推送到 `main`，等待 CI 全部通过。
3. 在该提交创建匹配版本的 `vX.Y.Z` 标签并推送，触发 CI 再次检查及发布。标签版本必须匹配元数据，且提交必须位于 `main` 历史上。
4. publish job 先发布核心，确认核心 wheel/sdist 可从 PyPI 查到且摘要一致，再发布完整包。
5. 检查两包文件全部完成后，才把版本标记为 App 更新源可用。App 更新源发布尚未接入本工作流。

也可手动运行 `release.yml`：选择 `main` 并设置 `publish=true`。默认手动运行只验证，不发布。发布只允许标签推送或显式开启发布的 main 手动运行，PR 和普通 main 推送均不会上传 PyPI。

PyPI 不提供两个包的原子发布。`scripts/pypi_release.py` 对重试逐文件检查：已存在且摘要相同才跳过，缺失才补发；同名文件内容不同则停止并要求新版本。不要直接开启不校验内容的 skip-existing，也不要覆盖已有 PyPI 版本。重试 publish job 应复用原 build artifact；重新构建若产生不同字节不能冒充旧文件。发布动作开启 PyPI provenance attestations；各第三方 Action 固定到已核实的提交。GitHub `pypi` environment 与 PyPI publisher 的 environment 必须一致。

用户当前操作统一见 [内置 Skill](skills/mcpywrap/SKILL.md)。发布验证记录、候选核查和跨仓库推进计划放在被忽略的 `.local-notes/`，不随源码包分发；长期发行规则维护在本页。候选 CI 的未签名桥接不用于验证正式签名登录流程。

## Windows 全局部署恢复验收

涉及全局包发布或归属恢复时，除完整测试外，运行 `tests/manual/lifecycle_dependency_audit.py --migration`，使用新建的隔离资料目录预置历史父项目双包链接，验证完整冲突、确认迁移、新代码加载、启动失败回滚、依赖变化及世界保留。不得提前清理真实用户的冲突链接，也不能以全新空白资料目录的正常启动替代升级场景。

Windows CI 额外以 `PYTHONUTF8=0`、`PYTHONIOENCODING=gbk` 运行部署恢复测试，覆盖默认编码下的 JSON、中文路径和终端确认。发布前保留单独的实机结果及当前提交信息；源码包应包含部署恢复文档、自动化测试与可复用验收脚本，过程日志留在忽略目录。

## 本机登录桥接开发

源代码位于 `native/mcs_auth`。CI 使用 x86 MSVC 和系统自带的 .NET Framework C# 编译器；本机开发也可使用 x86 TinyCC：

```powershell
python scripts/build_mcs_auth_bridge.py --cc <x86-tcc.exe> --output <输出目录>
```
