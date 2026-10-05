# 一条命令准备 QuMod

在已初始化的 Addon 项目中：

```powershell
mcpy add --qumod
```

只有一个 `modMain.py` 时自动选择其脚本目录；没有入口时创建 `MyScript`；有多个 Mod 时要求明确选择：

```powershell
mcpy add --qumod --script-dir MyMod
```

命令会声明外部代码库、获取固定提交、保存内容锁文件，并为**新脚本目录**生成 QuMod 的客户端、服务端及入口。已有目录的业务代码不改写；可根据下方示例手动接入，原版加载器与 QuMod 混用也不必覆盖原入口。

新 Mod 也可沿用模板命令：

```powershell
mcpy mod --framework qumod --name MyMod --script-dir MyMod
```

这两个入口共用同一个安装服务；下载或写入失败不会留下半份依赖声明。已声明的 QuMod 默认保留既有来源和提交，重复添加不会静默升级。

## 团队恢复与日常使用

提交 `pyproject.toml`、`mcpy-git.lock.json`、业务源码和 `.gitignore`。QuMod 的原始源码保存在用户级共享缓存，项目独立注册内容位于被忽略的 `.mcpy/git-projects/`；不会复制到业务源码目录。

其他开发者安装支持此功能的 mcpywrap 后，克隆项目、进入目录，只需：

```powershell
mcpy sync
```

随后 `mcpy run` 或 `mcpy package` 使用同一套组装逻辑，把框架安装到 `<脚本目录>/QuModLibs`。引擎、MC Studio 与工具环境依赖仍按原有方式准备；`sync` 不下载游戏，也不把工具 Python 的 site-packages 注入游戏。

无法访问 GitHub 时，可在首次添加时显式选择官方 Gitee：

```powershell
mcpy add --qumod --script-dir MyMod --qumod-source gitee
```

已有项目也可用该命令切换来源，保留其固定提交；新来源必须能提供该提交。来源变化会更新声明和锁文件，不自动回退到未经选择的第三方镜像。两种源的缓存身份独立，内容摘要可核对。

上述管理流程针对标准git_dependencies。既有code_libraries声明仍可同步恢复；快捷添加识别到它时保留原格式，不创建重复依赖。旧格式切换来源需显式编辑原声明并sync，或明确迁移到Git项目声明，不隐式重写。

移除代码库声明使用依赖列表中显示的名称：

```powershell
mcpy remove --git qumod-mymod
```

缓存与手写入口保留，需同步检查业务中的 QuMod 导入。不要把移除依赖理解为自动重写或删除业务代码。

## 图形和交互向导

- `mcpy add` / 交互式 `mcpy init` 中选择“常用Git依赖快捷添加”，再选择 qumod。
- `mcpy ui` → 添加新依赖 → Git 依赖 → 一键添加 QuMod，点击快捷按钮即可添加；下拉菜单可选来源或指定所属脚本目录。网络操作在后台进行。
- 依赖列表显示“Git依赖”、同步状态、来源、提交和安装位置，可移除选中声明。
- 克隆后的项目可点击“同步项目依赖”；等价于 `mcpy sync`，不会偷偷升级框架。

新入口会保留网易加载器需要的 `QMain`：

```python
# -*- coding: utf-8 -*-
from .QuModLibs.QuMod import EasyMod, QMain
MOD = EasyMod()
MOD.Server("Server")
MOD.Client("Client")
```

一个 Mod 内的功能模块共用其框架，多个独立 Mod 安装到各自的脚本目录。已有手工复制的 QuMod 会明确报冲突，向导不会擅自删除或覆盖它。

## 来源与版本依据

官方文档 https://qumod.cc/QuModLibs/modMain.html 同时链接：

| 来源 | 仓库 | 用途 |
|---|---|---|
| GitHub | https://github.com/GitHub-Zero123/QuModLibs | 维护者源码仓库，BSD-3-Clause，未归档 |
| Gitee | https://gitee.com/bili_zero123/qu_mod_libs | 官方文档指向的另一源码入口 |

预设固定提交 `a07430aaaa6dce5f1ef68de3fda52ea4b9366c2c`；该提交的 `Information.py` 标注 `Version = "1.4.3"`、`ApiVersion = 4`。不要用仓库当前 HEAD 代替项目锁定提交。

界面的“1.4.3”取自固定提交的源码元数据，不表示存在同名官方 Release。默认锁完整 SHA，不能将 master、当前 HEAD 或“最新”视为稳定版本契约。

仓库提供 Scripts/QuModLibs、Optional、Tools、Tests；没有供本工具直接消费的官方包索引或传递依赖描述。框架导入/模块裁剪工具不等于发布依赖仓库。工具以原始源码仓库作为来源，用通用 git_dependencies、导出描述、依赖图与内容锁补上获取、安装与恢复契约；旧code_libraries保持兼容；不要求上游为了我们的工具改造项目。

默认安装标准 `Scripts/QuModLibs`，包含其内置模块；不自动合并 Optional、不根据业务 import 自动裁剪、不运行上游 EXE。可选模块的独立依赖契约留给后续明确设计，不能根据目录名猜测。

稳定性保障来自“官方来源＋明确提交＋内容锁＋本地缓存＋兼容验证”，不是承诺任一托管平台永远在线。后续升级应先做兼容验证，再更新工具中的推荐提交；已有项目不会随工具升级自动改变版本。

内部实现边界：QuMod只存在于 framework_presets 的数据（来源、提交、目录、模板）和CLI快捷别名中。标准缓存、Git项目解析、依赖管理与组装代码不识别QuMod。任意其他仓库可用 `mcpy add --git` 接入同一流程，详见 [Git依赖结构](git-dependencies.md)。
