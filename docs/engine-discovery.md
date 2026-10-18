# 引擎发现

用户的诊断、版本和路径覆盖用法统一维护在 [Skill 安装与路由](../skills/mcpywrap/references/setup.md#windows-引擎发现与覆盖)。macOS 绑定与原生资源见 [平台说明](../skills/mcpywrap/references/macos-local.md)。

实现入口为 `mcstudio/discovery.py` 和 `engines/backend.py`。发现候选、资源预检与实际游戏启动分开；编辑器与游戏资源分别诊断，不以编辑器缺失阻止游戏。CLI/env/project 的路径来源和相对路径基准须保留，诊断返回候选及各资源的缺失原因，不静默替换用户选择的版本。
