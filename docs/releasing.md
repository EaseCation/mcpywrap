# 发布流程

主分支和 PR 运行 Windows Python 3.9、3.12、3.14 的自动化测试。通过后构建 wheel/sdist、运行严格元数据检查、检查产物内容，并在独立环境安装 wheel 验证 CLI 和模块导入。

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
