# 0.4.0 候选版验收与发布门槛

本分支用于 Windows 全功能复测，不会自动发布 PyPI。Python 包版本为 0.4.0；原生 macOS 运行包使用单独的不可变版本号。mcpy 安装、项目初始化与游戏资源准备是三个阶段，CLI/Qt 共用同一个后端。

## 完成度结论

- Windows：用户手动安装 MC Studio 并在其中下载引擎，这是正式设计。mcpy 负责发现、诊断和接入，不自动安装 MC Studio。新 PySide6 UI 和共用命令需要在真实 Windows 桌面复测。
- macOS：显式提供匹配 catalog 后，安装器可自动下载原生运行包、从网易取得 APK、校验和提取，随后直接运行。没有登录/手工复制游戏二进制的步骤。
- 原生启动器适配位于独立的 launcher/submodule 工作区，不包含在本 mcpy Git 分支；发布前需将对应源码/构建引用固定并推送，或分发已校验的完整对应源码归档。
- 尚未达到“普通用户仅安装 mcpy 即可使用默认源全自动下载”的公开发行状态：当前没有已发布的默认 HTTPS catalog/运行包源。保留 catalog_unconfigured 的准确提示，不填一个尚不存在的下载 URL。
- macOS 运行包当前 ad-hoc 签名，公开下载后的 Gatekeeper 行为和最低实际系统尚未验收。编译目标 11.0 不等于完整 Qt GUI 支持 11.0，Qt wheel 的系统/Python 要求以解析结果为准。
- macOS 离线 Addon 范围内工作；MCEditor、本地 Map、联网/身份登录以及 Windows 桌面截图/录制不伪装为可用。JSON UI 热更更新定义，需要重新注册/创建业务 UI 和回调。

## 包管理安装

正式发布后：

```sh
uv tool install --python 3.12 mcpywrap==0.4.0
mcpy --help
```

候选版尚未上传 PyPI。Windows 优先下载本分支 Actions 的 `distributions` artifact，解压后在 PowerShell 执行（替换为实际路径）：

```powershell
uv tool install --force --python 3.12 .\mcpywrap-0.4.0-py3-none-any.whl
mcpy --local doctor --capabilities --json
mcpy --local doctor --json
```

CI wheel 包含 Windows 原生辅助组件；直接从 Git 安装不自带这些构建产物，完整源码安装需先按 docs/releasing.md 编译。候选分支 CI 不读取 main 的签名密钥，因此登录桥接为未签名测试产物；正式 MCS 登录签名检查不能用这个候选 wheel 代替验证。其余 CLI/GUI、截图与录制按实际 capabilities 测试。

## 新用户流程

先创建项目目录，再运行：

```sh
mcpy --local --project <项目目录> --non-interactive init --name demo --type addon --json
mcpy --local --project <项目目录> --non-interactive mod --name DemoMod --json
```

Windows 已手动准备 MC Studio 引擎后，直接使用 run。macOS 首次运行需准备发布目录（APK 由网易下载，不需要 --apk）：

```sh
mcpy --local --non-interactive engine install --catalog <catalog.json的HTTPS地址或本地路径> --json
mcpy --local engine doctor --json
mcpy --local --project <项目目录> --non-interactive run --no-gui --detach --json
mcpy --local --project <项目目录> runtime capabilities --session <id> --json
mcpy --local --project <项目目录> logs --session <id> --source game --tail 200 --json
mcpy --local --project <项目目录> stop --session <id> --json
```

不带非交互/JSON 的人工 run 会打开 Qt6 开发界面；macOS 资源缺失时进入同一个安装对话框，完成后继续启动。纯命令模式不会弹出安装窗口或等待输入，按结构化 hint 显式安装。需要离线导入时，engine install 可加 --apk；版本错误应拒绝并保留已有环境。已有世界固定其运行包版本，更新运行包不自动迁移世界。

## Windows 复测清单

1. 干净 Python 3.12 环境安装 CI wheel，pip check；doctor 正确识别已安装/缺失/多个版本的 MC Studio，引导手动准备资源。
2. 中文及空格路径：init → mod → sync/build/package；本地依赖、Git 依赖、QuMod 增删及重开项目，依赖与模板内容正确。
3. 同一项目从 CLI 和 Qt 启动/复用/选择/新建实例；`--no-gui --detach --json` 不打开辅助窗；状态和日志返回同一会话。
4. Qt6 项目、依赖、实例、模板页；创建 Mod 子窗口不会启动第二个事件循环；按钮禁用/后台任务/错误提示正确。
5. 默认紧凑悬浮小窗、原生控件、置顶、移动到其他屏幕、展开/收起/缩放；长状态不撑宽。日志染色、搜索、协议详情与主界面同步；关闭小窗保留游戏。
6. 双端 Python，模块热更、监控端侧切换、重载世界；两视图只有一个 watcher，忙碌时不重复提交。JSON UI、粒子等按 capabilities 和实际画面验证。
7. runtime install、UI 快照/点击/滑动、玩家动作及编排，输入结束后释放；HBUI 不支持时准确报错。截图/录制/提帧/删除，前台回退与 background-only 按原规则。
8. Windows 远程 serve、认证 token、连接、日志、Python 与网络会话；失败不回退本机，不忽略不支持的等待参数。
9. MCS 身份登录单列验收：使用符合签名要求的原生组件，不能把 unsigned 候选包拒绝登录视为 Qt6 回归。
10. 正常退出、加载中停止、启动失败、重复 run、关闭主界面、附加外部会话；确认没有遗留自己启动的游戏/worker/日志小窗。Windows stop 沿用原停止机制，重要世界先从游戏正常保存退出。

每项记录 Python/Qt/引擎版本、实际结果、会话日志和复现步骤。发生结果未知时不重复发送业务脚本。

## 公开发布前

Windows 复测通过；发布可访问的 macOS 原生包及对应完整源码、catalog、摘要；配置并验证默认发布源；验证公开下载、系统签名体验及最低受支持系统。然后按原发布流程合并 main、签名构建，显式推送 v0.4.0 标签才发布 PyPI。分支版本号升级不等于已经公开发布。

## 本轮实际验收记录

2026-10-05，macOS 26.6.2：在全新 Python 3.12.11 venv 中安装实际 0.4.0 wheel，解析到 PySide6 6.11.2；pip 依赖检查、wheel/sdist 严格元数据检查和 118 个模块的源码/产物一致性检查通过。Windows 原生组件源码未改动，本机完整候选 wheel 复用 v0.3.19 成功 CI 的签名组件，并通过源码指纹/摘要检查；Git 分支 CI 仍从源码构建自己的测试组件。

全新资源目录中，网易接口解析、签名 URL、Range 响应及真实下载均确认；由于下载速度较慢，中止并保留续传文件，随后导入完全匹配的官方 APK，完成提取、签名校验、doctor、init、mod、源码包组装、原生启动及双端 Python 验收。两端读到同一世界，结束后游戏和 worker 已退出。未声称完整 2.2 GB 网络冷下载完成；预构建启动器使用显式本地 catalog，不能代替尚缺失的公开默认源验收。

冷启动发现的 queued 探针问题已修复：超过单次执行等待窗口时查询原 request_id，直到完成或达到总期限，不重复发送脚本。Windows CI 首轮发现的盘符路径解析和平台相关测试夹具已修正，Git 内容摘要顺序统一按 POSIX 相对路径，避免 Windows 大小写排序差异。
