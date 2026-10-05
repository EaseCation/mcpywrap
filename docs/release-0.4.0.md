# 0.4.0 候选版验收与发布门槛

本分支用于 Windows 全功能复测，不会自动发布 PyPI。Python 包版本为 0.4.0；原生 macOS 运行包使用单独的不可变版本号。mcpy 安装、项目初始化与游戏资源准备是三个阶段，CLI/Qt 共用同一个后端。

## 完成度结论

- Windows：用户手动安装 MC Studio 并在其中下载引擎，这是正式设计。mcpy 负责发现、诊断和接入，不自动安装 MC Studio。新 PySide6 UI 和共用命令需要在真实 Windows 桌面复测。
- macOS：mcpy run 从内置固定 HTTPS 发行目录自动下载原生运行包及网易开发者 APK，校验、提取后继续运行；用户无需填写 catalog/APK 路径。
- 原生启动器适配位于独立的 launcher/submodule 工作区，不包含在本 mcpy Git 分支；发布前需将对应源码/构建引用固定并推送，或分发已校验的完整对应源码归档。
- 原生运行包公开分发于 EaseCation/mcpelauncher-manifest 的 mcpy-runtime-v0.4.0-preview.1 Release，附带对应源码、catalog 和摘要；Python 0.4.0 的 PyPI 发布仍是单独步骤。
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

Windows 已手动准备 MC Studio 引擎后，直接使用 run。macOS 直接运行即可自动准备环境（APK 由网易下载）：

```sh
mcpy --local --non-interactive engine install --json  # 可选，run 也会自动安装
mcpy --local engine doctor --json
mcpy --local --project <项目目录> --non-interactive run --no-gui --detach --json
mcpy --local --project <项目目录> runtime capabilities --session <id> --json
mcpy --local --project <项目目录> logs --session <id> --source game --tail 200 --json
mcpy --local --project <项目目录> stop --session <id> --json
```

run 在终端完成首次安装、默认世界创建和配置路径提示；交互式本地启动默认显示共用调试小窗。--no-gui、--detach、--json 或 --non-interactive 抑制小窗。mcpy ui 才打开完整管理页、新建确认框及安装子窗口。AI 使用 --non-interactive run --no-gui --detach --json。高级用户可覆盖 --catalog 或通过 --apk 导入匹配资源。已有世界固定运行包版本，不自动迁移。

### 2026-10-06 macOS CLI 验收

在 Apple Silicon / macOS 26.6.2 上，清空相关环境变量，使用默认资源目录和独立 Addon 项目执行裸 `mcpy run`。公开 catalog 和原生运行包下载成功；网易 APK 的下载、重试、取消和续传路径已实际触发，但当天 CDN 出现 TLS 中断且速度偏低，未完成本轮全量联网下载。后续复用此前从官方下载且 SHA-256 一致的 3.10.100.299889 APK 缓存，完成校验、提取、自动兼容检查、默认世界创建和启动。此结果不等同于干净网络环境下的完整下载验收。

早期纯 CLI 验收中，前台打印真实 cppconfig 路径和修改提示，无 Qt 辅助窗口（后续已调整为交互启动默认带调试小窗）；游戏进入 `hud_screen`，客户端和服务端 Python 返回相同世界 ID。Ctrl+C 保存退出后可重新启动；`run --detach --json` 的 stdout 可解析为单个 JSON，并携带 config_path/config_hint。测试结束后关闭本轮游戏会话。自动测试共运行 518 项，24 项按平台条件跳过，其余通过；覆盖默认来源、CLI 自动安装、终端模板生成、Qt 自动安装完成继续、分段续传和空间估算。Skill 校验通过。

## Windows 复测清单

1. 干净 Python 3.12 环境安装 CI wheel，pip check；doctor 正确识别已安装/缺失/多个版本的 MC Studio，引导手动准备资源。
2. 旧 Git 锁通过普通 `mcpy sync` 自动验证、备份并更新为跨平台 v2 格式；Windows/macOS 共用同一份锁，两端需更新 mcpy。中文及空格路径：init → mod → sync/build/package；本地依赖、Git 依赖、QuMod 增删及重开项目，依赖与模板内容正确。
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
