# 发布流程

主分支和 PR 运行 Windows Python 3.9、3.12、3.14 的自动化测试，以及 macOS 的无 Qt 安装、项目构建与远程客户端测试。通过后构建 wheel/sdist、运行严格元数据检查、检查产物内容，并在独立环境安装 wheel 验证 CLI 和模块导入。

Windows CI 先用 MSVC 从 `native/mcs_auth` 编译 x86 登录桥接，再签名并通过构建产物交给测试和 Python 打包任务；编译后的 EXE/DLL 不提交到 Git。仓库只保留发布者公钥证书和指纹。
同一 native job 还会从 `native/window_capture` 编译 x64 后台截图辅助程序，生成 SHA-256 清单；测试和打包阶段校验二进制、源码及 wheel/sdist 内容。辅助程序不可用时运行时回退到前台截图。

从源码安装时，在 Windows x64 且已安装 Visual Studio x86/x64 C++ 工具的环境中先运行 `python scripts/build_all_native.py`，再执行 `pip install -e .` 或 `pip install .`。脚本一次编译 x86 登录桥接和 x64 截图程序到包目录；可用 `--output-root <目录>` 将结果放入隔离目录。登录桥接源码编译产物没有发布签名，正式登录能力仍应使用带签名的发布包。

仓库 Actions secrets：`MCS_BRIDGE_SIGNING_PFX` 保存 Base64 编码的加密 PFX，`MCS_BRIDGE_SIGNING_PASSWORD` 保存独立的强密码。只有 main／发布标签的签名步骤可读取它们，PR 只构建未签名测试产物。CI 将证书导入临时 runner 的个人证书库，签名后清理，不安装根信任。私钥、PFX 和密码均不进入日志或 artifact。

轮换签名身份时，需要同时更新这两个 secrets 和 `native/mcs_auth/publisher.cer`、`publisher.json`。脚本会拒绝与仓库固定公钥不匹配的签名证书；未签名产物不能进入 PyPI 发布任务。

发布凭据使用 PyPI Trusted Publishing，不在仓库或工作流中保存长期 API token。在 PyPI 项目 `mcpywrap` 的 Publishing 设置添加 GitHub publisher：

| 字段 | 值 |
|---|---|
| Owner | `EaseCation` |
| Repository | `mcpywrap` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

每次发布：

1. 同步修改 `pyproject.toml` 和 `mcpywrap/__init__.py` 中的版本，更新 CHANGELOG。
2. 将通过本地验证的提交推送到 `main`，等待 CI 全部通过。
3. 在该提交创建匹配版本的 `vX.Y.Z` 标签并推送，触发 CI 再次检查及发布。标签版本必须匹配元数据，且提交必须位于 `main` 历史上。
4. 检查 Actions 的 publish job 和 PyPI 新版本文件。发布失败时先排除原因；若是首次配置 publisher 尚未完成，可完成 PyPI 配置后重跑失败任务。

也可手动运行 `release.yml`：选择 `main` 并设置 `publish=true`。默认手动运行只验证，不发布。发布只允许标签推送或显式开启发布的 main 手动运行，PR 和普通 main 推送均不会上传 PyPI。

不要覆盖已有 PyPI 版本。发布动作开启 PyPI provenance attestations；各第三方 Action 固定到已核实的提交。GitHub `pypi` environment 与 PyPI publisher 的 environment 必须一致。
