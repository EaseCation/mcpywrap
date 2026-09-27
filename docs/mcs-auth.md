# MC Studio 登录身份

登录始终由 MC Studio 完成。`--mcs-auth` 只在本次启动读取已登录身份，不代填密码，不默认启用，也不会在失败时偷偷改用匿名身份。

```powershell
mcpy run --mcs-auth
mcpy connect 192.168.31.101 --port 19132 --mcs-auth
mcpy ui --mcs-auth
# Agent：后台单人测试，任何失败都返回 JSON，不弹窗或安装证书
mcpy --project D:\mods\demo --non-interactive run --mcs-auth --detach --json
```

本地与网络均支持 `--detach --json`，共用会话查询、日志和停止。GUI 登录支持单人项目，网络目标使用 CLI。

`mcpy doctor --mcs-auth --json` 可只读检查组件文件，不读取身份、不写缓存、不修改证书。组件具备不表示已登录或系统策略允许启用。

## 用户会看到什么

- MCS 未运行或未完成登录：提示先打开并登录；普通测试可去掉 `--mcs-auth`。
- 登录组件可正常启用：直接继续，无需安装证书。
- 组件被阻止且其完整签名只缺少根信任：人工交互时提供“信任此发布者并重试”，默认选择取消。确认前展示用途、信任范围、发布者、指纹与有效期。
- 安装后仍失败：停止重试，说明系统或组织策略仍可能阻止组件；不关闭 Windows 安全保护。
- 纯 CLI／Skill：`--non-interactive` 或 `--json` 不显示对话框、不读取确认输入、不安装证书。JSON 包含 `ok`、`error`、`hint`，身份失败另有 `code`，例如 `studio_unavailable`、`component_blocked`。

## 证书与隐私

组件使用项目自签名证书，不是公共 CA 认证的发布者。证书只在用户明确同意后加入 **当前用户**的“受信任的根证书颁发机构”，不会写入整机证书库。同一证书签署的其他代码也可能因此获得信任；这不是一次性的单文件例外，也不能覆盖 Smart App Control 或企业应用控制。

发布包只包含公共证书和签名文件，不包含私钥。证书指纹与文件 SHA-256 在 `mcpywrap/mcstudio/bridge_payload/manifest.json` 中；加载和证书提示前都会检查组件完整性。

桥接通过当前用户专用的一次性命名管道返回登录信息，不把 token 放入命令行或会话记录。游戏需要的身份仅写入本次运行配置，退出后删除；日志在写入磁盘前脱敏。MCS 必须保持运行；重新登录后应重新启动测试。

停止使用时，去掉 `--mcs-auth` 即可。若曾安装证书，可打开 `certmgr.msc`，在当前用户的“受信任的根证书颁发机构 → 证书”中找到 `mcpywrap Project Code Signing`，核对上述指纹后移除。不要移除其他证书。已加载的托管桥接程序集会随 MC Studio 退出而卸载。

## 开发与发布

源代码位于 `native/mcs_auth`。CI 使用 x86 MSVC 和系统自带的 .NET Framework C# 编译器；本机开发也可使用 x86 TinyCC：

```powershell
python scripts/build_mcs_auth_bridge.py --cc <x86-tcc.exe> --output <输出目录>
```

发布时由 CI 从 GitHub Actions secrets 取得加密 PFX 与密码，在临时 runner 中签署组件并清理私钥。仓库不保存私钥或编译后的组件，只保存源码与公钥校验信息。`scripts/check_mcs_auth_bridge.py` 检查源代码、产物、架构及发布者是否匹配；详见[发布流程](releasing.md)。

`MCPY_MCS_BRIDGE_DIR` 可指定开发组件目录；程序不会为任意外部组件提供证书信任安装。发布包的组件会缓存到用户目录的 `.local/share/mcpywrap/mcs-auth-bridge/<版本摘要>`，避免应用目录重定向造成外部终端找不到文件。
