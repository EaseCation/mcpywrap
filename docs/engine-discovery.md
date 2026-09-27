# 游戏启动与排查

先检查本机环境：

```powershell
mcpy doctor
mcpy doctor --json
```

诊断分别显示游戏、编辑器、Safaia 是否就绪。编辑器缺失不等于无法运行游戏。
默认优先使用 MC Studio 登记的安装，必要时搜索固定磁盘中的标准下载目录；不完整的版本会被跳过。

## 找不到游戏

确认已通过 MC Studio 下载引擎；自定义位置可指定下载目录或 EXE：

```powershell
mcpy doctor --mcs-download-path 'D:\MCStudioDownload'
mcpy run --game-executable 'D:\MCStudioDownload\game\MinecraftPE_Netease\3.10.0.420447\Minecraft.Windows.exe'
```

选择某个完整版本：

```powershell
mcpy run --engine-version 3.10.0.420447
```

已有实例保留原版本；显式指定可切换版本。`3.10` 不是 `3.10.*` 通配符；不存在时明确报错。

## 保存配置

| 项目中的 `[tool.mcpywrap]` 字段 | 本机环境变量 |
|---|---|
| `game_executable_path` | `MCPY_GAME_EXECUTABLE` |
| `mcs_download_path` | `MCPY_MCS_DOWNLOAD_PATH` |
| `engine_version` | `MCPY_ENGINE_VERSION` |

命令行优先于环境变量，环境变量优先于项目配置。团队通常只提交版本，本机路径放在环境变量。
项目配置的相对路径以项目为基准；CLI 和环境变量的相对路径以调用目录为基准。

EXE 不在版本目录时，需要另外声明 `engine_version`；这不验证二进制内部版本。
独立 EXE 仍需要下载目录中的皮肤和游戏用户数据，缺项按 doctor 的实际路径提示补齐。
同时配置 EXE 与下载目录时不能指向不同的标准安装。

## 不打开辅助界面

```powershell
mcpy --project D:\mods\demo --non-interactive run --no-gui --detach --json
mcpy --project D:\mods\demo logs --session <id> --tail 100 --json
mcpy --project D:\mods\demo stop --session <id> --json
```

只打开游戏窗口，日志写入返回的文件。`running` 表示进程存活，加载是否成功应查看项目日志或游戏画面。
Computer Use 只接手游戏画面；Qt 管理、模板及日志页留给人工操作。
以上示例是本地世界会话。网络连接可用 `mcpy connect <地址> --detach --json`，或配置服务器后执行 `run --detach --json`；同样使用返回的项目路径、会话 ID 读取日志、截图、输入和停止。临时 connect 不读取项目引擎配置，使用 CLI 参数或环境变量覆盖。
